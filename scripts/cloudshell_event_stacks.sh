#!/usr/bin/env bash
# Run in AWS CloudShell (admin session), after uploading infra/aws-gallery.yaml and infra/aws-face-search.yaml
# to the home folder (Actions → Upload file). For each event slug: the gallery stack in us-east-1 and the face
# search stack in sa-east-1.
#
# Sharing an existing publisher (one access key for every event; nothing new to store):
#   PUBLISHER_USER=event-photos-aws-community-day-belem-2026 bash cloudshell_event_stacks.sh cd-norte-2026-treino cd-norte-2026-jantar
# Without PUBLISHER_USER each event gets its own user event-photos-<slug>, and its access key is printed once at
# the end: store it with `aws configure --profile <aws_profile from event.json>`. A user that already has a key
# gets no new one, so the script can run again on an event to update its stacks.
#
# Updating a face search stack whose function changed resets the function's settings to the template's (the
# on/off switches that `face-search enable` wrote); the script says when that happened.
set -euo pipefail
[ $# -gt 0 ] || { echo "usage: [PUBLISHER_USER=<iam user>] $0 <event slug>..." >&2; exit 1; }
publisher="${PUBLISHER_USER:-}"
notes=$(mktemp)  # reminders repeated at the end
trap 'rm -f "$notes"' EXIT

# A stack whose first creation failed (ROLLBACK_COMPLETE) holds nothing and cannot be updated: delete it first.
clear_failed() {  # region stack
  if [ "$(aws cloudformation describe-stacks --region "$1" --stack-name "$2" --query "Stacks[0].StackStatus" \
          --output text 2>/dev/null)" = ROLLBACK_COMPLETE ]; then
    echo "   $2 failed before; deleting the empty stack"
    aws cloudformation delete-stack --region "$1" --stack-name "$2"
    aws cloudformation wait stack-delete-complete --region "$1" --stack-name "$2"
  fi
}
deploy() {  # region stack template params...
  local region=$1 stack=$2 template=$3; shift 3
  clear_failed "$region" "$stack"
  if ! aws cloudformation deploy --region "$region" --template-file "$template" --stack-name "$stack" \
         --parameter-overrides "$@" --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset; then
    echo "!! $stack failed; reasons:" >&2
    aws cloudformation describe-stack-events --region "$region" --stack-name "$stack" \
      --query "StackEvents[?contains(ResourceStatus, 'FAILED')].[LogicalResourceId,ResourceStatusReason]" --output text >&2
    exit 1
  fi
}

last_update() {  # region stack → when it last changed ("none" if it does not exist yet)
  aws cloudformation describe-stacks --region "$1" --stack-name "$2" --query "Stacks[0].LastUpdatedTime" \
    --output text 2>/dev/null || echo none
}

for slug in "$@"; do
  echo "== $slug: gallery (us-east-1)"
  deploy us-east-1 "event-photos-$slug" aws-gallery.yaml "EventSlug=$slug" "PublisherUser=$publisher"
  url=$(aws cloudformation describe-stacks --region us-east-1 --stack-name "event-photos-$slug" \
    --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue" --output text)
  echo "== $slug: face search (sa-east-1), origin $url"
  faces="event-photos-$slug-faces"
  before=$(last_update sa-east-1 "$faces")
  deploy sa-east-1 "$faces" aws-face-search.yaml "EventSlug=$slug" "GalleryOrigin=$url" "PublisherUser=$publisher"
  if [ "$before" != none ] && [ "$(last_update sa-east-1 "$faces")" != "$before" ]; then
    echo "!! $faces changed: its search function may be back to the template's settings. On the notebook, run" \
         "\`uv run event-photos face-search $slug enable --confirm-ai-opt-out\` again (or \`disable\` if it was off)."
    echo "!! $faces changed: run face-search $slug enable (or disable) again" >> "$notes"
  fi
done
if [ -z "$publisher" ]; then
  for slug in "$@"; do
    user="event-photos-$slug"
    if [ "$(aws iam list-access-keys --user-name "$user" --query "length(AccessKeyMetadata)" --output text)" != 0 ]; then
      echo "== $slug: $user already has an access key; none created"
      continue
    fi
    echo "== $slug: access key for $user (shown once)"
    aws iam create-access-key --user-name "$user" --query "AccessKey.[AccessKeyId,SecretAccessKey]" --output text
  done
fi
cat "$notes"  # the reminders again, so they are not lost above the key
