# ForgeOS v2 — App Store Design

Grounded in how CasaOS actually does it (researched), adapted to ForgeOS's
config-DB + generator architecture.

## What CasaOS does (the proven model we're adapting)
- Git-based catalog. The base syncs it locally (git pull), so the store
  works OFFLINE after first sync; updating is a pull.
- An app = a directory containing a docker-compose.yml plus icon/screenshots.
- Metadata rides in a compose extension block (x-casaos:) — title,
  description, category, author, icon, main service, port_map. Compose
  ignores x-* keys, so the file stays a valid compose file.
- name: is the unique store App ID, must match ^[a-z0-9][a-z0-9_-]*$.
- Magic WEBUI_PORT — platform allocates a free host port per app.
- No :latest tags — pinned image versions only.

## ForgeOS catalog
Separate repo: github.com/Dvalin21/forgeos-appstore
```
forgeos-appstore/
├─ catalog.json          # generated index (id, title, category, tagline, icon)
├─ categories.json
└─ apps/
   ├─ grafana/
   │  ├─ docker-compose.yml   # valid compose + x-forgeos block
   │  ├─ icon.png
   │  └─ screenshot-1.png
   └─ <app-id>/...
```

### App definition: docker-compose.yml + x-forgeos
- name: unique store App ID.
- services: pinned images, ports use ${WEBUI_PORT:-NNNN}, volumes under
  /srv/forgeos/apps/${APP_ID}/.
- x-forgeos: title, tagline, description, category, author, icon, main,
  port_map, architectures, tips.before_install.

### Platform-provided variables (substituted at install)
- WEBUI_PORT (free port the platform picks + remembers), APP_ID, TZ, PUID, PGID.

## How the base consumes the catalog
1. Catalog sync: git clone/pull to /var/lib/forgeos/appstore. Works offline.
2. Install: parse compose + x-forgeos (pydantic-validated), allocate a free
   WEBUI_PORT, substitute vars, write resolved compose to
   /srv/forgeos/apps/<id>/, docker compose up -d, record in config DB
   (apps: [...]), and HOOK INTO the nginx generator — add app.<domain> vhost
   to config DB + run nginx generator. App gets reverse-proxy + TLS for free.
3. Uninstall: compose down, remove vhost + re-render nginx, drop from config
   DB. Data dir kept by default.

## Config DB additions
apps: [ { id, version, webui_port, installed_at, enabled } ]
nginx vhost per app DERIVED from this list.

## First official apps
Grafana, Prometheus, Gotify (the things v2 removed from base).

## DECIDED (Keith)
1. Catalog repo: github.com/Dvalin21/forgeos-appstore (separate).
2. Install auto-creates an app.<domain> nginx vhost by default.
3. Official ForgeOS catalog only for v1 (code written so 3rd-party is easy
   to add later).
4. App data root: /srv/forgeos/apps/<id>/.

## Build sequence
1. forgeos_appstore.py: pydantic manifest models (compose + x-forgeos),
   parser/validator, catalog index reader. Pure + unit-testable.
2. Port allocator (pure: used ports -> free one) + tests.
3. Install/uninstall orchestration (compose up/down + config-DB record +
   nginx vhost via existing generator).
4. forgeos-app CLI (list / install / uninstall / status).
5. Seed forgeos-appstore repo with Grafana + Prometheus + Gotify.
6. Web UI.
