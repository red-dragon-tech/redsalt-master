#!/usr/bin/env bash
set -Eeuo pipefail
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
REPO=/srv/redsalt-master
REMOTE=origin
BRANCH=prd
TARGET='*'
LOCK=/run/redsalt-master-sync.lock
LOG=/var/log/redsalt-master-sync.log
STATE_DIR=/var/lib/redsalt
STATE_FILE=$STATE_DIR/last-prd-apply.sha
TMP_SWAP=/swapfile.redsalt-sync-temp
REPO_URL=https://github.com/red-dragon-tech/redsalt-master.git

mkdir -p "$STATE_DIR"
touch "$LOG"
chmod 0644 "$LOG"
exec 9>"$LOCK"
if ! flock -n 9; then
  exit 0
fi
exec >>"$LOG" 2>&1

ts() { date -Is; }
log() { printf '[%s] %s\n' "$(ts)" "$*"; }

ensure_repo() {
  if [ ! -d "$REPO/.git" ]; then
    rm -rf "$REPO"
    git clone --branch "$BRANCH" --single-branch "$REPO_URL" "$REPO"
  fi
  git -C "$REPO" remote set-url "$REMOTE" "$REPO_URL"
}

low_mem_kb() {
  awk '/MemTotal:/ {print $2}' /proc/meminfo
}

with_temp_swap() {
  local added=0
  if [ "$(low_mem_kb)" -lt 1048576 ] && ! swapon --show=NAME --noheadings | grep -qx "$TMP_SWAP"; then
    log "enabling temporary 1G swap for Salt apply on low-memory host"
    rm -f "$TMP_SWAP"
    fallocate -l 1G "$TMP_SWAP" || dd if=/dev/zero of="$TMP_SWAP" bs=1M count=1024 status=none
    chmod 600 "$TMP_SWAP"
    mkswap "$TMP_SWAP" >/dev/null
    swapon "$TMP_SWAP"
    added=1
  fi
  "$@"
  local rc=$?
  if [ "$added" -eq 1 ]; then
    log "disabling temporary swap"
    swapoff "$TMP_SWAP" || true
    rm -f "$TMP_SWAP"
  fi
  return "$rc"
}

apply_salt() {
  log "validating redsalt-master repo"
  /opt/saltstack/salt/bin/python3 "$REPO/scripts/validate.py"
  log "updating Salt fileserver"
  salt-run fileserver.update
  log "refreshing pillar for $TARGET"
  salt -t 120 "$TARGET" saltutil.refresh_pillar || true
  log "applying highstate to $TARGET"
  salt -t 300 "$TARGET" state.apply --state-output=changes
}

main() {
  log "sync tick start"
  ensure_repo
  git -C "$REPO" fetch --prune "$REMOTE" "$BRANCH"
  local desired current last_applied
  desired=$(git -C "$REPO" rev-parse "$REMOTE/$BRANCH")
  current=$(git -C "$REPO" rev-parse HEAD 2>/dev/null || true)
  last_applied=$(cat "$STATE_FILE" 2>/dev/null || true)
  log "current=${current:-none} desired=$desired last_applied=${last_applied:-none}"

  if [ "$current" != "$desired" ]; then
    log "updating checkout to $desired"
    git -C "$REPO" checkout "$BRANCH"
    git -C "$REPO" reset --hard "$REMOTE/$BRANCH"
    git -C "$REPO" clean -fdx
    chown -R root:root "$REPO"
  fi

  if [ "$last_applied" != "$desired" ]; then
    with_temp_swap apply_salt
    printf '%s\n' "$desired" > "$STATE_FILE"
    log "applied $desired"
  else
    log "already applied $desired"
  fi
  log "sync tick complete"
}

main "$@"
