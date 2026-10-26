#!/usr/bin/env bash
# Run in AWS CloudShell (admin session), after uploading infra/aws-gallery.yaml and infra/aws-face-search.yaml
# to the home folder (Actions → Upload file). For each event slug: the gallery stack in us-east-1 and the face
# search stack in sa-east-1.
#
# Sharing an existing publisher (one access key for every event; nothing new to store):
#   PUBLISHER_USER=event-photos-aws-community-day-belem-2026 bash cloudshell_event_stacks.sh cd-norte-2026-treino cd-norte-2026-jantar
# Without PUBLISHER_USER each event gets its own user event-photos-<slug>, and its access key is printed once at
# the end: store it with `aws configure --profile <aws_profile from event.json>`.
set -euo pipefail
[ $# -gt 0 ] || { echo "usage: [PUBLISHER_USER=<iam user>] $0 <event slug>..." >&2; exit 1; }
publisher="${PUBLISHER_USER:-}"

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

for slug in "$@"; do
  echo "== $slug: gallery (us-east-1)"
  deploy us-east-1 "event-photos-$slug" aws-gallery.yaml "EventSlug=$slug" "PublisherUser=$publisher"
  url=$(aws cloudformation describe-stacks --region us-east-1 --stack-name "event-photos-$slug" \
    --query "Stacks[0].Outputs[?OutputKey=='Url'].OutputValue" --output text)
  echo "== $slug: face search (sa-east-1), origin $url"
  deploy sa-east-1 "event-photos-$slug-faces" aws-face-search.yaml "EventSlug=$slug" "GalleryOrigin=$url" "PublisherUser=$publisher"
done
if [ -z "$publisher" ]; then
  for slug in "$@"; do
    echo "== $slug: access key for event-photos-$slug (shown once)"
    aws iam create-access-key --user-name "event-photos-$slug" \
      --query "AccessKey.[AccessKeyId,SecretAccessKey]" --output text
  done
fi
