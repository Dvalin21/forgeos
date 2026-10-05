# Reverse Proxy

`/reverse-proxy.html`. nginx routing a domain name to an internal service,
with optional TLS.

**forgeos.local is protected and cannot be removed** — it is the UI's own
entry point.

## Proxy hosts

Each host is a card: name, address, and chips for its features (HTTP,
HTTPS, WEBSOCKET, SYSTEM, SELF-SIGNED). Buttons:
- **pencil** — edit the upstream or options.
- **trash** — delete the host (`forgeos.local` refuses).

## Domains

A domain record issues a certificate. The A/CNAME record must already
point to this server at your DNS provider — ForgeOS requests the
certificate, it does not delegate DNS for you. **Add domain** starts the
flow.

## Raw configuration

The generated `nginx.conf`, checked with `nginx -t` before save. Reload
applies it.

## Verified

- One host exists by default: `forgeos-ui → 127.0.0.1:5080` with
  HTTP/HTTPS/WEBSOCKET/SYSTEM/SELF-SIGNED chips.
- `nginx -t` validation runs before any config save (`/api/nginx` routes).
