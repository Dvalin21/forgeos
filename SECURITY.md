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
