# Network

`/network.html`. Currently read-only for live values with explicit
undo-able actions for the rest — editing a static IP, DNS, DDNS, or a route
is possible, and every change runs through a confirm step so a bad
address change cannot lock you out.

## Read-only notice

The blue banner explains that editing is guarded. If you change an address,
the UI asks you to confirm within a set window, and reverts automatically
if you do not confirm.

## Interfaces

Each adapter gets a card: name, IPv4, MAC, state, MTU, and RX/TX totals.
**Configure** opens its settings.

## Global settings

- **Hostname** — applied with `hostnamectl` (Samba/NetBIOS and logs pick it
  up after a service restart).
- **Domain** — the DNS suffix, e.g. `example.com`.
- **DNS servers** — comma-separated resolvers.
- **Default gateway** — read-only per interface here; instances change via
  interface editing.

**Apply** writes the values via `timedatectl`/`resolvectl` equivalents and
logs a `settings.update` event. **Reset** reloads the live values.

## Dynamic DNS

If you have a public hostname, this keeps it pointed at the NAS when your
public IP changes. **Not configured** means nobody set it up. **Set up**
asks for provider, hostname, and credentials, then records a DDNS test.

## Routing table

Kernel routes: destination, gateway, interface, metric, source
(`static`/`kernel`). **Add route** appends one and logs `net.route.add`.
Row trash icon deletes with a log of `net.route.delete`.

## Verified

- Interfaces card shows `ens18 · 10.0.0.69/24 · UP`.
- Save/apply flows log `net.interface.apply/confirm` entries (visible in
  the Activity Log).
- Routing table lists the default route, the /24, and docker0.
