# ForgeOS Reverse-Proxy Manager — Design (V-030)

**Status:** PLANNED (Phase 5). This is a design record, not yet built.
**Goal:** an NPM-class reverse-proxy manager that is *easier* than NPM —
outcome-level hardening behind checkboxes, not raw nginx knobs. "So easy a
caveman can do it."

Built on what already exists: the config-DB (`/etc/forgeos/config.json`) +
the nginx generator. A proxy host is just another entry the generator renders
to a vhost — same pure-render/atomic-apply/reload pattern as everything else.

---

## 1. Core model

A **proxy host** = (incoming hostname) → (upstream target), plus a set of
toggled behaviors. Two upstream kinds:
- **Internal service / app** (e.g. a ForgeOS app on 127.0.0.1:PORT)
- **External URL** (proxy to another box / service on the LAN or WAN)

Config-DB gets a `proxy_hosts: list[ProxyHost]` section. The nginx generator
learns to render these alongside the control-plane vhost.

## 2. Per-host options (checkboxes in the WebUI)

### Already-common (NPM has these)
- Websockets support
- Caching (static asset cache with sane defaults)
- HSTS / force-HTTPS
- HTTP/2
- Block common exploits (the NPM rule set: SQLi/path-traversal/etc.)

### ForgeOS value-add — OUTCOME toggles (the differentiator)
- **Block AI scrapers** — maintained blocklist of AI crawler user-agents
  (GPTBot, CCBot, ClaudeBot, Bytespider, etc.) + `robots.txt` injection.
  Available **per-host AND as a global default** (your explicit ask).
- **Block common exploit patterns** — beyond NPM's: known scanner paths
  (`/.env`, `/wp-login.php`, `/.git`), suspicious query strings.
- **Rate limiting** — per-IP request caps with a friendly "requests/sec"
  slider, not raw `limit_req_zone` syntax.
- **Geo-blocking** (optional, needs GeoIP DB) — allow/deny by country.
- **Basic-auth gate** — put a quick username/password in front of any host.
- **Bot/crawler challenge** — optional JS challenge for unknown bots.
- **Maintenance mode** — serve a static "be right back" page per host.
- **Access lists** — allow/deny by IP/CIDR (reuse the security-tier lan_cidr).

### Global options (apply to all proxy hosts unless overridden)
- Global "Block AI scrapers"
- Global exploit blocking
- Global rate-limit baseline
- Default security-headers bundle

## 3. Certificates — Let's Encrypt DNS-01, multi-domain, multi-registrar

The local control-plane stays self-signed (V-010, by design). PUBLIC-facing
proxy hosts get real certs via **DNS-01** (works behind NAT / private IP —
no public port 80 needed):

- Support **multiple domains** across **one OR more registrars** (explicit
  ask). Each domain carries its own DNS-provider credentials.
- Provider plugins via certbot's DNS plugins (Cloudflare, Route53, Namecheap,
  deSEC, etc.) OR lego if we want a single binary. Decision deferred to build.
- A "Domains" section in config-DB: each domain = {name, provider, cred-ref}.
  Creds live in the keystore (0600), never in config.json.
- Auto-renew via systemd timer (already the pattern for osbackup).
- A proxy host picks which domain it lives under; cert is issued/renewed for
  that hostname automatically.
- Wildcard certs supported (DNS-01 enables them) — one `*.domain` cert can
  cover many proxy hosts.

## 4. WebUI flow (the "caveman" bar)

1. "Add Proxy Host" → type the incoming domain, pick upstream (app dropdown or
   URL field).
2. Pick the domain/cert (or self-signed for LAN-only).
3. Checkboxes: the outcome toggles above, sensible defaults pre-checked
   (block AI scrapers ON, exploit blocking ON, HSTS ON).
4. Save → config-DB updated → nginx generator renders the vhost → cert issued
   (DNS-01) if a public domain → nginx reload. Done.

Advanced users get a "Custom nginx directives" escape hatch (free-text,
validated with `nginx -t` before apply) so power isn't lost.

## 5. Implementation notes (when we build it, Phase 5)

- New config-DB models: `ProxyHost`, `ProxyDomain`, global `ProxyDefaults`.
- Extend the nginx generator: render proxy-host vhosts; a snippets library for
  each toggle (ai-scrapers.conf, exploits.conf, ratelimit template, etc.)
  included conditionally.
- New `certbot`/DNS-01 orchestration module (issue/renew/revoke), creds from
  keystore, multi-domain registry.
- API routes + UI page; reuse the generator/apply/reload path.
- Tests: render snapshots per toggle combination; DNS-01 orchestration mocked;
  `nginx -t` validation in CI on rendered output.
- Blocklists (AI scrapers, exploit patterns) shipped as data files, updatable.

## 6. Open questions (resolve at build time)
- certbot DNS plugins vs lego (single binary, cleaner multi-provider)?
- Where AI-scraper / exploit blocklists are sourced + how they update.
- GeoIP DB licensing (MaxMind requires an account) — make it optional.
- How custom directives are sandboxed/validated beyond `nginx -t`.

---

This doc exists so the vision is recorded and designed, not improvised. It is
NOT built yet — Phase 2 (resolution + secret perms) and Phases 3-4 come first.
