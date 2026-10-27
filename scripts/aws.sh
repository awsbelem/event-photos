#!/usr/bin/env bash
# Run events on the processing instance (infra/aws-processing.yaml) from this machine, over SSM Session Manager.
#
#   scripts/aws.sh setup                        # once: models and event.local.json to the work bucket, image
#   scripts/aws.sh size <type> [<fallback>...]  # stop, change the instance type, start (next type if none free)
#   scripts/aws.sh run <slug> [--no-publish] [--restore]
#                                               # a round: update, review over a tunnel, publish, save the state
#   scripts/aws.sh attach                       # back into a round after the connection dropped
#   scripts/aws.sh status | stop | shell
#   scripts/aws.sh pull-state <slug> | push-state <slug>   # fallback: run the event on this machine instead
#
# Needs the AWS CLI with the events' profile (AWS_PROFILE, default event-photos) and the Session Manager plugin.
# Everything about the instance comes from the stack's outputs; nothing about it is written to the repository.
set -euo pipefail

PROFILE="${AWS_PROFILE:-event-photos}"
REGION=us-east-1
STACK="${EVENT_PHOTOS_STACK:-event-photos-processing}"
PORT=8766
TMUX_SESSION=event-photos
BRANCH=stable  # what CI promotes once main is green (.github/workflows/ci.yml): a failing commit never runs here
# Kept out of the state copy: refilled from the upload inbox on every round.
STATE_EXCLUDES=(--exclude 'uploads/*' --exclude 'uploads-dated/*' --exclude 'inbox/*')

usage() { sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
say() { echo "→ $*"; }
die() { echo "$*" >&2; exit 1; }

cd "$(dirname "$0")/.."
action="${1:-}"; [[ -n "$action" ]] || usage; shift

for tool in aws python3; do command -v "$tool" >/dev/null || die "falta o comando $tool"; done
awsc() { aws --profile "$PROFILE" --region "$REGION" "$@"; }
output() {
  awsc cloudformation describe-stacks --stack-name "$STACK" \
    --query "Stacks[0].Outputs[?OutputKey=='$1'].OutputValue" --output text
}
IID=$(output InstanceId) || die "não achei a stack $STACK (perfil $PROFILE): ela foi implantada? (README, Processing on AWS)"
BUCKET=$(output WorkBucket)

check_slug() {
  [[ "${1:-}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "slug inválido: ${1:-}"
  [[ -f "events/$1/event.json" ]] || die "events/$1/event.json não existe"
}
need_plugin() {
  command -v session-manager-plugin >/dev/null ||
    die "falta o Session Manager plugin: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html"
}
instance() { awsc ec2 describe-instances --instance-ids "$IID" --query "Reservations[0].Instances[0].$1" --output text; }
json() { python3 -c 'import json,sys; print(json.dumps({k: [v] for k, v in zip(sys.argv[1::2], sys.argv[2::2])}))' "$@"; }

ensure_running() {
  case "$(instance State.Name)" in
    running) ;;
    pending) awsc ec2 wait instance-running --instance-ids "$IID" ;;
    stopping) awsc ec2 wait instance-stopped --instance-ids "$IID"; start ;;
    stopped) start ;;
    *) die "a instância está $(instance State.Name)" ;;
  esac
  for _ in $(seq 60); do  # the SSM agent comes up a little after the instance
    [[ "$(awsc ssm describe-instance-information --filters "Key=InstanceIds,Values=$IID" \
          --query 'InstanceInformationList[0].PingStatus' --output text)" == Online ]] && return
    sleep 5
  done
  die "a instância não respondeu ao SSM em 5 minutos"
}
start() {
  say "ligando a instância ($(instance InstanceType))"
  awsc ec2 start-instances --instance-ids "$IID" >/dev/null
  awsc ec2 wait instance-running --instance-ids "$IID"
}

# A script run as ec2-user on the instance, its output printed here; fails when the script fails. It runs from a
# file with stdin closed: fed through stdin, a command that reads it (docker compose run) swallowed the rest.
remote() {
  local b64 id status tries=0
  b64=$(printf 'set -euo pipefail\n%s\n' "$1" | base64 | tr -d '\n')
  id=$(awsc ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript \
        --parameters "$(json commands "f=\$(mktemp); echo $b64 | base64 -d > \$f; chmod 644 \$f; sudo -u ec2-user -H bash -l \$f < /dev/null; s=\$?; rm -f \$f; exit \$s" executionTimeout 3600)" \
        --query Command.CommandId --output text)
  while :; do
    status=$(awsc ssm get-command-invocation --command-id "$id" --instance-id "$IID" --query Status --output text 2>/dev/null || echo Pending)
    case "$status" in Pending|InProgress|Delayed) sleep 3 ;; *) break ;; esac
    (( ++tries < 1300 )) || die "o comando na instância passou de uma hora"
  done
  awsc ssm get-command-invocation --command-id "$id" --instance-id "$IID" --query StandardOutputContent --output text | sed '/^$/d'
  if [[ "$status" != Success ]]; then
    awsc ssm get-command-invocation --command-id "$id" --instance-id "$IID" --query StandardErrorContent --output text >&2
    die "falhou na instância ($status)"
  fi
}

# Workers and limits for the instance's size: one worker per physical core, as long as each has ~1.2 GB.
env_for_type() {
  local cores vcpus mib workers
  read -r cores vcpus mib < <(awsc ec2 describe-instance-types --instance-types "$1" \
    --query 'InstanceTypes[0].[VCpuInfo.DefaultCores,VCpuInfo.DefaultVCpus,MemoryInfo.SizeInMiB]' --output text)
  workers=$(( (mib - 1536) / 1229 )); (( workers > cores )) && workers=$cores; (( workers < 1 )) && workers=1
  printf 'EVENT_PHOTOS_WORKERS=%s\nEVENT_PHOTOS_MEMORY=%sm\nEVENT_PHOTOS_CPUS=%s\nEVENT_PHOTOS_MAX_LONG_SIDE=4032\n' \
    "$workers" "$((mib - 1024))" "$vcpus"
}

# Code, models, settings and image up to date for one event; its state from the bucket when the instance has none.
prepare() {  # slug restore
  local slug=$1 env
  env=$(env_for_type "$(instance InstanceType)")
  if [[ -f "events/$slug/event.local.json" ]]; then  # this machine is where it is edited (face-search, contact)
    awsc s3 cp --only-show-errors "events/$slug/event.local.json" "s3://$BUCKET/events/$slug/event.local.json"
  fi
  say "preparando a instância"
  remote "
cloud-init status --wait >/dev/null 2>&1 || true
cd ~/event-photos
git fetch -q origin $BRANCH && git reset -q --hard FETCH_HEAD && git log -1 --format='   código ($BRANCH): %h %s'
aws --profile event-photos s3 sync --only-show-errors s3://$BUCKET/models/ models/
ls models/*.onnx >/dev/null 2>&1 || { echo 'faltam os modelos no bucket: rode scripts/aws.sh setup' >&2; exit 1; }
if aws --profile event-photos s3 ls s3://$BUCKET/events/$slug/event.local.json >/dev/null; then
  aws --profile event-photos s3 cp --only-show-errors s3://$BUCKET/events/$slug/event.local.json events/$slug/
fi
if [ '$2' = yes ]; then rm -rf out/events/$slug; fi
if [ ! -d out/events/$slug ] && aws --profile event-photos s3 ls s3://$BUCKET/out/$slug/ >/dev/null; then
  echo '   estado restaurado do bucket'
  aws --profile event-photos s3 sync --only-show-errors s3://$BUCKET/out/$slug/ out/events/$slug/
fi
printf '%s\n' '$env' > .env
echo \"   \$(grep WORKERS .env)\"
cat > ~/round.sh <<'ROUND'
$(round_script)
ROUND
docker compose build -q"
}

# One round on the instance; its state goes to the bucket even when the round fails. Written there as a file
# because the session's command passes through `sudo -i`, which leaves `$` unescaped: that command holds none.
round_script() {
  sed "s|@BUCKET@|$BUCKET|" <<'SCRIPT'
#!/bin/bash
# Written by scripts/aws.sh on every run: bash round.sh <slug> [--publish]
slug=$1; shift
cd ~/event-photos || exit 1
docker compose run --rm --service-ports event-photos event "$slug" "$@"
status=$?
echo "→ salvando o estado no bucket de trabalho"
if aws --profile event-photos s3 sync --only-show-errors --delete --no-follow-symlinks \
     --exclude 'uploads/*' --exclude 'uploads-dated/*' --exclude 'inbox/*' \
     "out/events/$slug" "s3://@BUCKET@/out/$slug"; then
  echo "   estado salvo"
fi
if [ "$status" -eq 0 ]; then echo "rodada concluída"; else echo "a rodada falhou (código $status)"; fi
read -rp "Enter para fechar " _
SCRIPT
}
# Inside tmux, so the round survives a dropped connection.
round_command() { echo "sudo -iu ec2-user tmux new-session -A -s $TMUX_SESSION 'bash round.sh $1 $2'"; }

tunnel() {
  ! (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null || die "a porta $PORT já está em uso aqui (outro túnel aberto?)"
  # In a process group of its own: the CLI runs session-manager-plugin as a grandchild, which outlived a plain
  # kill and kept the port taken. Closing the group closes the whole tunnel.
  setsid aws --profile "$PROFILE" --region "$REGION" ssm start-session --target "$IID" \
    --document-name AWS-StartPortForwardingSession \
    --parameters "$(json portNumber "$PORT" localPortNumber "$PORT")" >/dev/null 2>&1 &
  TUNNEL_PID=$!
  trap 'kill -- -"$TUNNEL_PID" 2>/dev/null; true' EXIT
}
interactive() { awsc ssm start-session --target "$IID" --document-name AWS-StartInteractiveCommand --parameters "$(json command "$1")"; }

case "$action" in
  setup)
    say "modelos → bucket de trabalho"
    awsc s3 sync --only-show-errors models/ "s3://$BUCKET/models/"
    for f in events/*/event.local.json; do
      if [[ -f "$f" ]]; then awsc s3 cp --only-show-errors "$f" "s3://$BUCKET/$f"; fi
    done
    ensure_running
    say "imagem (a primeira vez leva alguns minutos)"
    remote "cloud-init status --wait >/dev/null 2>&1 || true
echo \"   compose \$(docker compose version --short)\"
cd ~/event-photos
git fetch -q origin $BRANCH && git reset -q --hard FETCH_HEAD && git log -1 --format='   código ($BRANCH): %h %s'
aws --profile event-photos s3 sync --only-show-errors s3://$BUCKET/models/ models/
docker compose build -q"
    echo "pronto. Uma rodada: scripts/aws.sh run <slug>"
    ;;
  size)
    [[ $# -gt 0 ]] || usage
    if [[ "$(instance State.Name)" != stopped ]]; then
      say "desligando"; awsc ec2 stop-instances --instance-ids "$IID" >/dev/null
      awsc ec2 wait instance-stopped --instance-ids "$IID"
    fi
    for type in "$@"; do
      awsc ec2 modify-instance-attribute --instance-id "$IID" --instance-type "Value=$type"
      if awsc ec2 start-instances --instance-ids "$IID" >/dev/null 2>/tmp/event-photos-start.err; then
        awsc ec2 wait instance-running --instance-ids "$IID"
        say "rodando como $type"; exit 0
      fi
      grep -q InsufficientInstanceCapacity /tmp/event-photos-start.err || { cat /tmp/event-photos-start.err >&2; exit 1; }
      echo "   sem $type disponível agora; tentando o próximo"
    done
    die "nenhum dos tipos estava disponível; a instância ficou desligada"
    ;;
  run)
    need_plugin
    slug="${1:-}"; check_slug "$slug"; shift
    publish=--publish restore=no
    for flag in "$@"; do
      case "$flag" in --no-publish) publish="" ;; --restore) restore=yes ;; *) usage ;; esac
    done
    ensure_running
    prepare "$slug" "$restore"
    tunnel
    say "rodando; abra no navegador o link de revisão que aparecer. Se a conexão cair: scripts/aws.sh attach"
    interactive "$(round_command "$slug" "$publish")"
    ;;
  attach)
    need_plugin
    ensure_running
    tunnel
    interactive "sudo -iu ec2-user tmux attach -t $TMUX_SESSION"
    ;;
  status)
    echo "instância: $(instance State.Name), $(instance InstanceType)"
    echo "bucket de trabalho: $BUCKET"
    awsc s3 ls "s3://$BUCKET/out/" | sed 's/^ *PRE /estado salvo: /' || echo "nenhum estado salvo ainda"
    if [[ "$(instance State.Name)" == running ]]; then
      remote "df -h / | awk 'NR==2 {print \"disco: \" \$3 \" de \" \$2 \" usados\"}'
tmux has-session -t $TMUX_SESSION 2>/dev/null && echo 'rodada em andamento: scripts/aws.sh attach' || true"
    fi
    ;;
  stop)
    awsc ec2 stop-instances --instance-ids "$IID" >/dev/null && say "desligando"
    ;;
  shell)
    need_plugin
    ensure_running
    interactive "sudo -iu ec2-user bash -l"
    ;;
  pull-state)
    slug="${1:-}"; check_slug "$slug"
    awsc s3 sync --only-show-errors "s3://$BUCKET/out/$slug/" "out/events/$slug/"
    echo "estado de $slug em out/events/$slug. Depois de rodar aqui: scripts/aws.sh push-state $slug"
    ;;
  push-state)
    slug="${1:-}"; check_slug "$slug"
    [[ -d "out/events/$slug" ]] || die "não há out/events/$slug aqui"
    awsc s3 sync --only-show-errors --no-follow-symlinks "${STATE_EXCLUDES[@]}" "out/events/$slug/" "s3://$BUCKET/out/$slug/"
    echo "estado enviado. A próxima rodada na instância precisa usá-lo: scripts/aws.sh run $slug --restore"
    ;;
  *) usage ;;
esac
