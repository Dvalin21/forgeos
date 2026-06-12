#!/usr/bin/env bash
# ForgeOS v2 — bootstrap
#
# The ONLY bash in the v2 installer. Its single job: make sure Python and the
# ForgeOS package deps exist, then hand off to the Python installer which does
# all the real work (seed config DB, run generators, apply toggles).
#
# Deliberately tiny — this is the opposite of the v1 19-module bash monolith.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "ForgeOS v2 installer must run as root." >&2
    exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

echo "==> ForgeOS v2 installer"
echo "    repo: $REPO_ROOT"

# 1. Python + pip (the only thing we truly need before Python takes over).
echo "==> Ensuring Python is present"
apt-get update -qq
apt-get install -y -qq python3 python3-pip python3-venv git

# 2. Install ForgeOS + its declared deps from pyproject (the deps-file rule:
#    never hand-pick; pyproject is the source of truth).
echo "==> Installing ForgeOS Python package + deps"
pip install --quiet --break-system-packages "${REPO_ROOT}[rustfs]"

# 3. Hand off to the Python installer.
echo "==> Handing off to the Python installer"
exec python3 "${REPO_ROOT}/install/v2/forgeos-install-cli.py" "$@"
