# Apps & Containers

`/apps.html`. The ForgeOS app catalog plus a view of installed containers
and systemd services.

## Top stats

Four counts across the top: services running, containers running, catalog
entries, updates available.

## Tabs

- **Catalog** — app cards. Each card names the app, a one-line description,
  and its availability: *Available* (can be installed) or *Installed*.
  **Install** pulls the container image and starts the service;
  **Uninstall** stops it and removes it. Installed apps also show on the
  Dashboard's My Apps row.
- **Containers** — every running container (image, status). This is the
  Docker/Incus-backed view.
- **Services** — systemd units exposed through ForgeOS.

## Verifying your install

After **Install**, check the Dashboard — the app's tile should show a
green running dot. After **Uninstall**, its card returns to *Available*.

## Verified

- Catalog shows Jellyfin, Plex, Navidrome, and 20+ others; Photoprism and
  Navidrome are *Installed*.
- The audit trail shows `docker.run` and `docker.wipe` entries for the
  Photoprism/Navidrome install and a later Code-Server removal.
