# VM facts — verified against the test box

Everything here was confirmed by running a command on `10.0.0.69`, not inferred.
Re-verify any of it with `./scripts/vm.sh facts` rather than trusting this file.
That command prints every line below from the live box.

Note: `import samba_api` in a plain shell fails with `JwtSecretMissingError` —
the module needs the service's env. Use `ls dist-packages/` instead.

## Install layout

The API does **not** run from `dist-packages`:

| Thing | Where | How it was confirmed |
|---|---|---|
| API entrypoint | `/opt/forgeos/forgeos-api.py` | `systemctl show forgeos-api -p ExecStart` |
| Installer | `/opt/forgeos/forgeos_install.py` | only copy on the box |
| Static assets | `/opt/forgeos/web/desktop/` | served from the tree; edits are live immediately |
| API modules (`samba_api`, `nfs_api`, …) | `/usr/local/lib/python3.13/dist-packages/` | `ls /usr/local/lib/python3.13/dist-packages/*.py` (53 files) |

`dist-packages/forgeos-api.py` does not exist. Copying a deploy there is a no-op
that looks like success — this happened once.

`scripts/vm.sh` encodes the mapping so it never has to be recalled.

## Access

- SSH: `keith@10.0.0.69`, key-based (`BatchMode=yes` works, no password prompt).
- `sudo` requires a password; `sudo -n` fails. Password is read from
  `~/.config/forgeos/vm_sudo` (chmod 600, **never committed**).
- `docker` needs sudo too — plain `docker images` as `keith` returns nothing,
  which reads like "no images" rather than "permission denied".

## SSH rate limiting

`ufw status` shows `22/tcp LIMIT 10.0.0.0/24`. This is a rate limit, **not a
ban**. It rejects with a TCP reset, so the client reports
`Connection refused` — which looks identical to sshd being down and is easy to
misdiagnose.

Consequences:

- Bursts of separate `ssh`/`scp` calls get refused. A handful of quick
  file pushes is enough.
- `scripts/vm.sh` holds one `ControlMaster` socket (`ControlPersist=900`), so
  a whole deploy costs a single TCP connection.
- Do not "fix" this by loosening ufw. It is correct.

## Service sandbox

`forgeos-api` runs with `ProtectSystem=strict`, so `/etc` is read-only except
the paths in `ReadWritePaths`. Those bind mounts are set up once at service
start; a `-`-prefixed entry whose directory does not exist is skipped and stays
read-only for the service's lifetime. Generators that write under `/etc` depend
on the installer pre-creating those directories — see `RUNTIME_DIRS` in
`install/v2/forgeos_install.py` and the test that keeps the two in step.

## Known box state

- `/etc/exports.d` was created by hand, because the installer predates the fix
  that creates it (`3ca6ac8`). A clean install gets it automatically.
- `/etc/exports` still holds a pseudo-root line written by an older installer,
  so `exportfs -ra` warns about a duplicate entry against
  `/etc/exports.d/forgeos.exports`. Box state, not a code defect.
- fail2ban was stopped by the operator. Its bans do not survive a stop, but a
  rule written before the stop does.