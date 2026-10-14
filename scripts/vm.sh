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
EOF
  # Only the entrypoint lives in $APP — ExecStart runs it, which makes $APP
  # sys.path[0], so a single stray .py there shadows dist-packages (the
  # §2 incident; `vm.sh shadow` guards it). The other old entrypoints are
  # pip console scripts ([project.scripts] → /usr/local/bin) and the
  # installer runs from a repo tree — none of them are deployed to $APP.
  # API modules import from dist-packages (verified: python3 -c 'import
  # samba_api' resolves there), NOT from $APP — but the ENTRYPOINT is
  # $APP/forgeos-api.py, which is what systemd ExecStart runs. Copying the
  # entrypoint to dist-packages is a no-op that looks like success.
  for f in "$ROOT"/src/*.py; do
    b="$(basename "$f")"
    # __init__.py marks src/ as a package in the REPO; there is no
    # `src` package on the box, and dropping it into dist-packages
    # root would mark site-packages itself as a package.
    case "$b" in forgeos-api.py|forgeos-app.py|forgeos-generate.py|__init__.py) continue ;; esac
    printf 'src/%s\t%s/%s\n' "$b" "$DIST" "$b"
  done
  for f in "$ROOT"/src/generators/*.py; do
    [ -e "$f" ] || continue
    b="generators/$(basename "$f")"
    printf '%s\t%s/%s\n' "src/$b" "$DIST" "$b"
  done
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
      /tmp/.forgeos-pathmap - | sort > "$rsum" || true

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
    # Match the FIRST field (repo-relative path) against the FULL manifest,
    # independently per path. Narrowing `todo` after each match meant the
    # first path removed everything the later ones needed, so
    # `deploy a.py b.py` reported "no manifest entry matches: b.py".
    # Plain loop on purpose: the two-file awk form read only the first file
    # here and silently returned nothing.
    local want line keep="" all="$todo" sel=""
    for want in "${paths[@]}"; do
      keep=""
      while IFS= read -r line; do
        if [ "${line%%$'\t'*}" = "$want" ]; then
          keep="$keep$line"$'\n'
        fi
      done <<< "$all"
      [ -n "$keep" ] || { echo "no manifest entry matches: $want" >&2; exit 1; }
      sel="$sel$keep"
    done
    todo="$sel"
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
  cmd_check || exit 1
  # Syntax pre-flight: a module with a syntax error must never be able to
  # brick the API. Compile every deployed .py on the box; on failure, leave
  # the running service alone (old code beats no code) and exit 1.
  local pyfail=0
  while IFS=$'\t' read -r l r; do
    [ -n "$l" ] || continue
    case "$r" in
      *.py)
        ssh_vm "python3 -c \"import ast,sys; ast.parse(open('$r').read())\"" >/dev/null 2>&1 || {
          echo "SYNTAX ERROR in $l — service NOT restarted (old code kept)" >&2
          pyfail=1
        } ;;
    esac
  done <<< "$todo"
  [ "$pyfail" -eq 0 ] || exit 1
  # Restart + prove the API is back (the header documents deploy as
  # copy + restart + verify; a copy without a restart silently changes
  # nothing — the same trap as the §2 shadowing incident).
  echo "restarting forgeos-api"
  ssh_vm "bash -s" <<EOF
printf '%s\n' "$(sudo_pw)" | sudo -S -p '' systemctl restart forgeos-api
for _ in \$(seq 1 20); do
  curl -sk https://127.0.0.1/health >/dev/null 2>&1 && exit 0
  sleep 1
done
echo "API did not answer /health within 20s of restart" >&2
exit 1
EOF
  echo "API restarted and healthy"
}

cmd_check_shadow() {
  # The entrypoint runs $APP/forgeos-api.py, so $APP is sys.path[0] and ANY
  # module file left there wins over the installer's dist-packages copy. That
  # shadowing silently ignored a correct deploy: the code landed in
  # dist-packages, the service kept importing a stale copy from $APP, and the
  # symptom was "the new code is deployed but nothing changed".
  ensure_conn
  local out
  out=$(ssh_vm "D=$DIST; A=$APP; n=0; for f in \$A/*.py \$A/generators/*.py; do
          [ -e \"\$f\" ] || continue
          b=\$(basename \"\$f\")
          case \"\$b\" in forgeos-api.py|forgeos-app.py|forgeos-generate.py) continue ;; esac
          if [ -f \"\$D/\$b\" ] || [ -f \"\$D/generators/\$b\" ]; then echo \"\$b\"; n=\$((n+1)); fi
        done; echo \"SHADOW_COUNT=\$n\"" 2>/dev/null)
  local files count
  files=$(printf '%s\n' "$out" | grep -v '^SHADOW_COUNT=' || true)
  count=$(printf '%s\n' "$out" | sed -n 's/^SHADOW_COUNT=//p')
  if [ "${count:-0}" -gt 0 ]; then
    echo "SHADOWING: $count module file(s) in $APP override dist-packages:" >&2
    printf '  %s\n' $files >&2
    echo "  the service will import THESE, not what you just deployed." >&2
    echo "  fix: remove them from $APP (they are duplicates of dist-packages)" >&2
    return 1
  fi
  echo "no shadowing in $APP (0 stray module files)"
}

case "${1:-}" in
  facts)  shift; cmd_facts "$@" ;;
  check)  shift; cmd_check "$@" ;;
  shadow) shift; cmd_check_shadow "$@" ;;
  deploy) shift; cmd_deploy "$@" ;;
  exec)   shift; ensure_conn; ssh_vm "$@" ;;
  *) sed -n '2,20p' "$0"; exit 1 ;;
esac