#!/usr/bin/env bash
# Run in AWS CloudShell (admin session), after the event stacks exist (cloudshell_event_stacks.sh) and after
# uploading infra/aws-processing.yaml to the home folder (Actions → Upload file). Creates or updates the
# processing stack in us-east-1 with every event given, so its instance can work on all of them:
#
#   PUBLISHER_USER=<the events' iam user> bash cloudshell_processing_stack.sh <event slug>...
#
# Run it again with the full list whenever an event is added.
set -euo pipefail
[ $# -gt 0 ] && [ -n "${PUBLISHER_USER:-}" ] || {
  echo "usage: PUBLISHER_USER=<iam user> $0 <event slug>..." >&2; exit 1; }
region=us-east-1
stack=event-photos-processing
account=$(aws sts get-caller-identity --query Account --output text)

# The rights each event stack grants its publisher; an event without face search has no -faces policy.
arns=()
for slug in "$@"; do
  for kind in gallery faces; do
    arn="arn:aws:iam::$account:policy/event-photos-$slug-$kind"
    if aws iam get-policy --policy-arn "$arn" >/dev/null 2>&1; then arns+=("$arn"); else echo "   (no $kind policy for $slug)"; fi
  done
done
[ ${#arns[@]} -gt 0 ] || { echo "no event policy found: deploy the event stacks first" >&2; exit 1; }
(IFS=,; echo "== $stack: ${#arns[@]} event policies"; joined="${arns[*]}"
  if ! aws cloudformation deploy --region "$region" --template-file aws-processing.yaml --stack-name "$stack" \
         --parameter-overrides "PublisherUser=$PUBLISHER_USER" "EventPolicyArns=$joined" \
         --capabilities CAPABILITY_NAMED_IAM --no-fail-on-empty-changeset; then
    echo "!! $stack failed; reasons:" >&2
    aws cloudformation describe-stack-events --region "$region" --stack-name "$stack" \
      --query "StackEvents[?contains(ResourceStatus, 'FAILED')].[LogicalResourceId,ResourceStatusReason]" --output text >&2
    exit 1
  fi)
echo "== done. On the notebook: scripts/aws.sh setup"
