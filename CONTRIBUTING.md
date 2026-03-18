# Contributing to ForgeOS

Thank you for considering contributing. ForgeOS is designed to be modular and straightforward to extend.

---

## Ways to Contribute

- **Bug reports** — open an Issue with the label `bug`. Include your OS version, kernel version, and the relevant section of `/var/log/forgeos-install.log`.
- **Hardware compatibility** — if you've tested on hardware not listed in the README, open a PR updating the compatibility table.
- **New modules** — see the Module Development section below.
- **Bug fixes** — fork, fix, test with `test-forgeos.sh`, open a PR.
- **Documentation** — improvements to `docs/` are always welcome.

---

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/forgeos.git
cd forgeos

# Lint all shell scripts
find install/ -name "*.sh" | xargs shellcheck -S warning

# Lint Python
python3 -m py_compile src/forgeos-api.py src/forgeos-filedb.py

# Run tests against a running install
sudo bash test-forgeos.sh --quick
```

---

## Module Development

Each installer module is a standalone bash script that sources `lib/common.sh`. The pattern is:

```bash
#!/usr/bin/env bash
source "$(dirname "$0")/../lib/common.sh"
source "$FORGENAS_CONFIG"

install_thing() {
    step "Installing thing"
    apt_install some-package
    # ... configure ...
    enable_service thing
    forgenas_set "THING_ENABLED" "yes"
    info "thing installed"
}

install_thing
```

Functions available from `lib/common.sh`:

| Function | Description |
|---|---|
| `step "msg"` | Section header in installer output |
| `info "msg"` | Green success line |
| `warn "msg"` | Yellow warning line |
| `die "msg"` | Red fatal error, exits |
| `apt_install pkg...` | Install packages (auto-updates cache once) |
| `apt_install_optional pkg...` | Install packages, warn on failure |
| `enable_service svc...` | systemctl enable + start |
| `forgenas_set KEY val` | Write to `/etc/forgeos/forgeos.conf` |
| `forgenas_get KEY [default]` | Read from conf |
| `gen_password [len]` | Generate secure random password |
| `wait_for_port host port [tries]` | Wait for TCP port to open |
| `get_system_disk` | Returns the disk the OS is installed on |

---

## Pull Request Checklist

Before opening a PR:

- [ ] All shell scripts pass `shellcheck -S warning`
- [ ] All Python files pass `python3 -m py_compile`
- [ ] New modules added to the module list in `install/install.sh`
- [ ] New CLIs added to the test suite in `test-forgeos.sh`
- [ ] No secrets, passwords, or credentials in any committed file
- [ ] Module is idempotent (safe to run twice)
- [ ] If a new service is added: UFW rule, systemd service, and nginx vhost are included

---

## Coding Style

**Shell:**
- `#!/usr/bin/env bash` + `set -euo pipefail`
- 4-space indentation
- Local variables with `local`
- Functions lowercase_with_underscores
- Constants UPPERCASE

**Python:**
- PEP 8
- Type hints on function signatures
- `async`/`await` for all I/O in FastAPI routes

---

## Commit Messages

```
module(05-coral): add pcie_aspm=off fallback for missing apex devices

Adds forgeos-coral fix-aspm command that patches GRUB when
/dev/apex_* devices don't appear after first boot.

Closes #42
```

Format: `scope(file-or-area): short description`

---

## Security Issues

Do **not** open public Issues for security vulnerabilities. Email the maintainer directly or use GitHub's private security reporting feature. See [SECURITY.md](SECURITY.md).
