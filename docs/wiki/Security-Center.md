# Security Center

`/security.html`. Intrusion prevention and automatic security updates.

## Intrusion prevention (fail2ban)

Four jails watch for repeated failed logins and ban the source:
- **sshd** — SSH
- **nginx-http-auth** — web UI sign-in through nginx
- **forgeos-api** — direct API sign-in
- **recidive** — repeat offenders get banished for a week

Each row shows the jail name, active bans, and state (`Active`).

### TUNING

- **10m**-style fields: max-retry and find-time windows, bantime.
- The note below states exactly how the numbers combine — a ban needs more
  than the retry count from a host within the find-time window.
- **Save & apply** renders the jail files and reloads fail2ban.

## Automatic security updates

- **Install security updates automatically** — on, backed by Debian
  `unattended-upgrades` (security origin only).
- **Reboot automatically when required** — off by default, some kernel
  updates need a reboot.

**Save & apply** persists the toggles.

## Verified

- All four jails active, zero bans at time of verification.
