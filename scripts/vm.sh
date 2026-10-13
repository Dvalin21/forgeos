#!/usr/bin/env bash
# ForgeOS — single entry point for talking to the test VM.
#
# Exists because the install layout used to live only in the operator's head.
# That produced a real bug: files were copied to
# dist-packages/forgeos-api.py while the service actually runs
# /opt/forgeos/forgeos-api.py, and the deploy "succeeded".
#
# The mapping below is the layout, written down once. `check` diffs it against
# the VM, `deploy` applies it. Nothing else needs to know where things go.
#
#   ./scripts/vm.sh check          verify VM matches repo; exit 1 on drift
#   ./scripts/vm.sh deploy [args]  copy + restart + verify (args = paths, default all)
#   ./scripts/vm.sh facts          print the verified environment facts
#   ./scripts/vm.sh exec <cmd>     run one command over the shared connection
#
# Every path here was confirmed against the running box, not inferred.

set -euo pipefail

VM="${FORGEOS_VM:-keith@10.0.0.69}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOCK="${FORGEOS_VM_SOCK:-/tmp/forgeos-vm-ssh}"
PW_FILE="${FORGEOS_VM_PWFILE:-$HOME/.config/forgeos/vm_sudo}"
PYVER="3.13"
DIST="/usr/local/lib/python${PYVER}/dist-packages"
APP="/opt/forgeos"

# The layout. One line per file: <repo-relative-path> <tab> <absolute-remote-path>
manifest() {
  cat <<EOF
src/forgeos-api.py	$APP/forgeos-api.py
install/v2/forgeos_install.py	$APP/forgeos_install.py
EOF
  # static assets are served straight out of the tree and must always match
  for f in "$ROOT"/web/desktop/*.html "$ROOT"/web/desktop/js/*.js \
           "$ROOT"/web/desktop/css/*.css; do
    [ -e "$f" ] || continue
    printf '%s\t%s/%s\n' "${f#"$ROOT"/}" "$APP" "${f#"$ROOT"/}"
  done
}

# Modules under src/ import from dist-packages (verified: python3 -c
# 'import samba_api' resolves there) but are NOT checked by default — the VM
# legitimately lags on modules nobody has touched. Deploy them by name:
#   ./scripts/vm.sh deploy src/nfs_api.py
# Never glob these: src/__init__.py would land on dist-packages/__init__.py.

sudo_pw() {
  [ -r "$PW_FILE" ] || { echo "no sudo password file at $PW_FILE" >&2; exit 1; }
  cat "$PW_FILE"
}

# One TCP connection, reused. The VM rate-limits ssh (ufw 22/tcp LIMIT
# 10.0.0.0/24); a burst of separate scp/ssh calls gets refused. See docs/VM-FACTS.md.
ensure_conn() {
  if [ -S "$SOCK" ] && ssh -O check -S "$SOCK" "$VM" 2>/dev/null; then return 0; fi
  rm -f "$SOCK"
  ssh -o ControlMaster=auto -o ControlPath="$SOCK" -o ControlPersist=900 \
      -o StrictHostKeyChecking=no -o BatchMode=yes "$VM" true
}

ssh_vm()  { ensure_conn; ssh -o ControlPath="$SOCK" -o BatchMode=yes "$VM" "$@"; }
scp_vm()  { ensure_conn; scp -o ControlPath="$SOCK" -o BatchMode=yes "$@"; }

cmd_facts() {
  ensure_conn
  # ssh forwards no environment by default, and putting the password in the
  # remote command line would expose it in ps. Ship it as a mode-600 temp file
  # and delete it in the same command.
  ensure_conn
  scp_vm "$PW_FILE" "$VM:/tmp/forgeos-pw" >/dev/null
  ssh_vm "chmod 600 /tmp/forgeos-pw; FORGEOS_PW=\$(cat /tmp/forgeos-pw); rm -f /tmp/forgeos-pw; export FORGEOS_PW APP='$APP' DIST='$DIST'; bash -s" <<'FEOF'
set -u
s() { sudo -S "$@" <<<"$FORGEOS_PW" 2>/dev/null; }
echo "host          : $(hostname)"
echo "ssh user      : $(id -un)"
echo "sudo          : $(sudo -n true 2>/dev/null && echo nopasswd || echo 'password required')"
echo "api ExecStart : $(systemctl show forgeos-api -p ExecStart --value | sed 's/.*path=\([^ ;]*\).*/\1/')"
echo "api workingdir: $(systemctl show forgeos-api -p WorkingDirectory --value)"
echo "web root      : $APP/web/desktop"
echo "dist-packages : $DIST"
echo "api modules   : $(s ls $DIST/*.py | wc -l) file(s)"
echo "exports.d     : $(s test -d /etc/exports.d && echo present || echo MISSING)"
echo "ufw ssh rule  : $(s ufw status | grep -E '^22' || echo none)"
FEOF
}

cmd_check() {
  ensure_conn
  local lsum=/tmp/.forgeos-local-sums rsum=/tmp/.forgeos-remote-sums
  local rel rem
  rel="$(manifest | cut -f1)"
  rem="$(manifest | cut -f2 | tr '\n' ' ')"   # remote cmd is one line

  : > "$lsum"
  while IFS= read -r l; do
    [ -f "$ROOT/$l" ] || { echo "MISSING LOCAL: $l" >&2; return 1; }
    md5sum "$ROOT/$l" | awk -v p="$l" '{print $1"  "p}' >> "$lsum"
  done <<< "$rel"
  sort -o "$lsum" "$lsum"

  # key BOTH sides by the repo-relative path: the VM reports absolute paths
  manifest | awk -F'\t' '{print $2"\t"$1}' > /tmp/.forgeos-pathmap
  ssh_vm "sudo -S md5sum $rem" <<<"$(sudo_pw)" 2>/dev/null \
    | awk 'NR==FNR{m[$1]=$2;next}{ if ($2 in m) print $1"  "m[$2]; else print $1"  UNMAPPED:"$2 }' \
      /tmp/.forgeos-pathmap - | sort > "$rsum"

  if [ ! -s "$rsum" ]; then
    echo "VM returned no checksums - refusing to report success" >&2
    return 1
  fi
  if grep -q UNMAPPED "$rsum"; then
    echo "remote path not in manifest (install layout changed?):" >&2
    grep UNMAPPED "$rsum" | sed 's/^/  /' >&2
    return 1
  fi
  if diff -q "$lsum" "$rsum" >/dev/null; then
    echo "IN SYNC ($(wc -l < "$rsum" | tr -d ' ') files)"
    return 0
  fi
  echo "DRIFT (repo vs VM):" >&2
  diff -u "$lsum" "$rsum" | sed 's/^/  /' >&2
  echo "  ./scripts/vm.sh deploy" >&2
  return 1
}

cmd_deploy() {
  local paths=("$@")
  [ ${#paths[@]} -eq 0 ] && paths=()
  local todo; todo="$(manifest)"
  if [ ${#paths[@]} -gt 0 ]; then
    # -F -x: literal, whole-line match. A trailing "|" separator here used
    # to add an empty alternative that matched every manifest line, so a
    # one-file deploy rewrote the whole tree.
    # Match the FIRST field (repo-relative path); the second is the remote
    # path. Plain loop: the two-file awk form silently read only the first
    # file here, which made every filter come back empty.
    local want line keep=""
    for want in "${paths[@]}"; do
      keep=""
      while IFS= read -r line; do
        [ "${line%%$'\t'*}" = "$want" ] && keep="$keep$line"$'\n'
      done <<< "$todo"
      [ -n "$keep" ] || { echo "no manifest entry matches: $want" >&2; exit 1; }
      todo="$keep"
    done
  fi
  ensure_conn
  local n=0
  while IFS=$'\t' read -r l r; do
    [ -n "$l" ] || continue
    [ -f "$ROOT/$l" ] || { echo "missing local file: $l" >&2; exit 1; }
    scp_vm "$ROOT/$l" "$VM:/tmp/forgeos-payload" >/dev/null
    ssh_vm "bash -s" "$r" <<EOF
set -euo pipefail
printf '%s\n' "$(sudo_pw)" | sudo -S cp /tmp/forgeos-payload '$r'
rm -f /tmp/forgeos-payload
EOF
    n=$((n+1))
    printf '  copied %s\n' "$l"
  done <<< "$todo"
  echo "copied $n file(s); verifying by checksum"
  # verification is the only thing allowed to print success
  cmd_check
}

case "${1:-}" in
  facts)  shift; cmd_facts "$@" ;;
  check)  shift; cmd_check "$@" ;;
  deploy) shift; cmd_deploy "$@" ;;
  exec)   shift; ensure_conn; ssh_vm "$@" ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac