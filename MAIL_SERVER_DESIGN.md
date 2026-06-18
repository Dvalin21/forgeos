# ForgeOS Mail Server — Design Stub (FUTURE, not scheduled)

**Status:** STUB. Not planned for a near phase. This exists to record the
naming decision so the schema we build now doesn't paint us into a corner.

## Why this stub exists
While building V-011 (mDNS resolution), Keith flagged: a mail server's
hostname must match its public DNS MX/PTR record (e.g. `mail.example.com`),
which can NEVER be the `.local` mDNS LAN name. If "the box's name" were a
single value, adding mail later would force renaming the box and breaking
Samba/SSH/etc. So we separated names NOW.

## The three-names model (already in config-DB as `NamingConfig`)
A ForgeOS box has THREE distinct names. They coincide on a simple LAN box and
DIVERGE the moment mail or a public proxy host appears:

1. **system_hostname** — OS identity (`hostnamectl`). Samba NetBIOS, logs, SSH
   key on it. ForgeOS NEVER silently changes it.
2. **lan_name** — LAN discovery name, mDNS `<hostname>.local`. The local web
   UI. (V-011, Option 3.)
3. **public_fqdn** — globally-resolvable, DNS-backed. EMPTY until a real
   domain exists. Used by the reverse-proxy manager (real TLS) AND a future
   mail server (MX/PTR/HELO). NEVER `.local`.

A mail server reads `public_fqdn`. Setting it does NOT touch hostname or
lan_name. No migration, no rename — that's the whole point of doing this now.

## What a mail server would need (external, NOT things ForgeOS can grant)
Self-hosted mail is hard because of requirements OUTSIDE the box:
- **PTR / reverse DNS** for the public IP must match the HELO/FQDN — set by
  the ISP/hosting provider. Residential IPs usually can't, which is the #1
  reason home mail fails deliverability.
- **MX, SPF, DKIM, DMARC** in the public DNS zone the operator controls.
- A static, reputation-clean public IP (many residential IPs are on blocklists).
- Port 25 outbound often blocked by ISPs.

ForgeOS's honest role: make the *server-side* easy (Postfix/Dovecot config,
DKIM keygen, the records to copy-paste into DNS), and be CLEAR that PTR + IP
reputation are the operator's/ISP's job. Over-promising "host your own email!"
on a residential line would be dishonest.

## Likely shape (when/if scheduled)
- Reuse config-DB + generator pattern: a MailConfig section, generators for
  Postfix/Dovecot/OpenDKIM.
- public_fqdn drives the mail hostname; a "DNS records to set" panel in the UI
  (MX/SPF/DKIM/DMARC values to paste into the registrar).
- Integrate with the reverse-proxy manager's DNS-01 cert story for the
  submission/IMAPS TLS cert (same public domain).
- Strong default anti-abuse (no open relay, auth required, rate limits).

## Decision recorded
Schema carries `public_fqdn` from Phase 2 onward (empty). Mail, if built,
slots into it. This stub is the contract: **no future feature renames the
box or repurposes the LAN name.**
