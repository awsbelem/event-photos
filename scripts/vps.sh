#!/usr/bin/env bash
# Run an event on a server from this machine, through your own ssh (your keys, your agent).
#
#   scripts/vps.sh <user@host> setup <slug>   # once per server and event: code, models, local settings, past run
#   scripts/vps.sh <user@host> run <slug>     # every round: update, build, run, review over a tunnel, publish
#   scripts/vps.sh <user@host> run <slug> --no-publish
#
# The destination is only ever an argument (or EVENT_PHOTOS_VPS): nothing about the server is written to the
# repository. The script never reads or copies ~/.aws or ssh keys; AWS access on the server is set up there,
# by you (see README, "Running on a server").
set -euo pipefail

REPO_URL="https://github.com/awsbelem/event-photos.git"
REMOTE_DIR="${EVENT_PHOTOS_DIR:-event-photos}"  # relative to the remote home
PORT=8766

usage() { sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }

dest="${1:-${EVENT_PHOTOS_VPS:-}}"; [[ $# -gt 0 ]] && shift
action="${1:-}"; slug="${2:-}"; flag="${3:-}"
[[ -n "$dest" && -n "$action" && -n "$slug" ]] || usage
[[ "$slug" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "slug inválido: $slug" >&2; exit 2; }
cd "$(dirname "$0")/.."
[[ -f "events/$slug/event.json" ]] || { echo "events/$slug/event.json não existe" >&2; exit 2; }

# One connection for every step: a key passphrase or password is asked once.
SSH_OPTS=(-o ControlMaster=auto -o "ControlPath=$HOME/.ssh/cm-event-photos-%C" -o ControlPersist=120)
remote() { ssh "${SSH_OPTS[@]}" "$dest" "$@"; }
send() { rsync -a -e "ssh ${SSH_OPTS[*]}" "$@"; }

update_code() {
  echo "→ código ($REPO_URL)"
  # An older copy sent with rsync has no .git: adopt it in place; untracked files (out/, models/) stay.
  remote "set -e; mkdir -p '$REMOTE_DIR' && cd '$REMOTE_DIR'
    if [ ! -d .git ]; then git init -q && git remote add origin '$REPO_URL'; fi
    git fetch -q origin main && git reset -q --hard origin/main && git log -1 --format='   %h %s'"
}

send_local_settings() {
  # Gitignored values (removal contact, face search on/off) and the models, which are not in git either.
  echo "→ configurações locais e modelos"
  send --chmod=F600 "events/$slug/" "$dest:$REMOTE_DIR/events/$slug/" --include='event.local.json' --exclude='*'
  send models/ "$dest:$REMOTE_DIR/models/"
}

build() {
  echo "→ imagem"
  remote "set -e; mkdir -m 700 -p ~/.aws; cd '$REMOTE_DIR' && docker compose build -q"
}

case "$action" in
  setup)
    update_code
    send_local_settings
    # A run started here carries its state (review, minors marks, face index state, credits): send it once,
    # so the server neither reprocesses everything nor loses those marks. Never overwrite the server's own.
    if [[ -d "out/events/$slug" ]]; then
      if remote "test -e '$REMOTE_DIR/out/events/$slug'"; then
        echo "→ o servidor já tem out/events/$slug; nada enviado"
      else
        echo "→ estado da última execução (out/events/$slug)"
        remote "mkdir -p '$REMOTE_DIR/out/events/$slug'"
        send "out/events/$slug/" "$dest:$REMOTE_DIR/out/events/$slug/"
      fi
    fi
    build
    remote "test -s ~/.aws/credentials || test -s ~/.aws/config" || cat >&2 <<EOF

Falta o acesso à AWS no servidor. Configure lá, digitando a chave você mesmo:
  ssh -t $dest 'cd $REMOTE_DIR && docker run --rm -it -v ~/.aws:/home/app/.aws --entrypoint aws event-photos configure --profile event-photos'
EOF
    echo "pronto. Rode: scripts/vps.sh $dest run $slug"
    ;;
  run)
    publish="--publish"
    case "$flag" in "") ;; --no-publish) publish="" ;; *) usage ;; esac
    update_code
    send_local_settings
    build
    echo "→ rodando; abra no navegador o link de revisão que aparecer (o túnel já está aberto)"
    ssh "${SSH_OPTS[@]}" -t -o ExitOnForwardFailure=yes -L "$PORT:127.0.0.1:$PORT" "$dest" \
      "cd '$REMOTE_DIR' && docker compose run --rm --service-ports event-photos event '$slug' $publish"
    ;;
  *) usage ;;
esac
