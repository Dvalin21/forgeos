#!/usr/bin/env bash
# iso/payload/build-payload.sh — bake a versioned ForgeOS tarball for the ISO.
#
# Version comes from pyproject.toml (single source of truth — no separate
# VERSION file to drift out of sync with it).
#
# Excludes dev/build cruft so the baked payload is lean: .git (history isn't
# needed on the installed box — bootstrap.sh installs from the unpacked tree,
# not via git), __pycache__, tests/ (not needed on a running appliance),
# node_modules if present, and any existing iso/ output artifacts (the
# payload doesn't need to contain itself).
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    echo "Run as your normal user, not root — this only reads/writes the repo and iso/ output." >&2
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${REPO_ROOT}/iso"

VERSION="$(python3 -c "
import tomllib
with open('${REPO_ROOT}/pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
" 2>/dev/null || python3 -c "
import re
with open('${REPO_ROOT}/pyproject.toml') as f:
    m = re.search(r'^version\s*=\s*\"([^\"]+)\"', f.read(), re.M)
    print(m.group(1))
")"

if [[ -z "$VERSION" ]]; then
    echo "Could not read version from pyproject.toml — refusing to build an unversioned payload." >&2
    exit 1
fi

OUT_FILE="${OUT_DIR}/forgeos-payload-${VERSION}.tar.gz"

echo "==> Baking ForgeOS payload v${VERSION}"
echo "    repo: ${REPO_ROOT}"
echo "    out:  ${OUT_FILE}"

tar -czf "${OUT_FILE}" \
    -C "${REPO_ROOT}" \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache' \
    --exclude='tests' \
    --exclude='node_modules' \
    --exclude='iso/forgeos-payload*.tar.gz' \
    --exclude='.venv' \
    --exclude='venv' \
    .

SIZE="$(du -h "${OUT_FILE}" | cut -f1)"
echo "==> Done: ${OUT_FILE} (${SIZE})"

# A stable, unversioned symlink/copy name so late_command and build-iso.sh
# (I4) don't need to know the exact version string at ISO-build time.
cp -f "${OUT_FILE}" "${OUT_DIR}/forgeos-payload.tar.gz"
echo "==> Also wrote ${OUT_DIR}/forgeos-payload.tar.gz (stable name for the ISO build)"
