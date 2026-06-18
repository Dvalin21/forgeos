# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| 1.x (current) | ✅ Active |

## Reporting a Vulnerability

**Do not open a public GitHub Issue for security vulnerabilities.**

Use one of these methods:

1. **GitHub private security reporting** — go to the Security tab on the repo and click "Report a vulnerability"
2. **Email** — contact the maintainer directly (see profile)

### What to include

- Description of the vulnerability
- Steps to reproduce
- Potential impact
- Your suggested fix (if any)

### Response timeline

- Acknowledgement within 48 hours
- Status update within 7 days
- Fix released within 30 days for critical issues

## Security Design Notes

ForgeOS is designed with these principles:

- No backdoors of any kind
- No telemetry or phone-home
- All sensitive data encrypted at rest (Restic AES-256, optional gocryptfs for ePHI)
- GDPR compliant — no age verification, exportable audit logs
- TLS mandatory on all externally-accessible services
- Default-deny UFW firewall; services only opened as modules install
- Secrets generated with `openssl rand` — never hardcoded
- `/etc/forgeos/forgeos.conf` is mode 600 root-only

## TLS / certificates (v2)

The **local control-plane** web UI uses a **self-signed certificate** by
design. A home NAS on a private `.local`/RFC1918 address cannot obtain a
publicly-trusted certificate (no public DNS, no reachable port 80), so a
self-signed cert is the correct, honest choice for LAN access. Trust it once
on your devices, or reach the box by IP.

Publicly-trusted certificates (Let's Encrypt, DNS-01, multi-domain) are a
feature of the **reverse-proxy manager** for *public-facing proxied hosts* —
not the control-plane installer. See `REVERSE_PROXY_DESIGN.md`.

## Secret file permissions

Every secret the installer writes is mode `0600` and root-owned:
`/etc/forgeos/api.env` (JWT), `api-users.json` (password hashes),
`config.json`, and `wireguard/server.key`. The installer's `secaudit` phase
verifies this on the real system after install and fails the install if any
secret is loosely permissioned — intent is not trusted, it is proven.

## Network exposure

The API backend binds `127.0.0.1` only; nginx is the sole front door and
terminates TLS. The backend is never directly reachable from the LAN in plain
HTTP. Override with `FORGEOS_HOST` only if you understand the exposure.
