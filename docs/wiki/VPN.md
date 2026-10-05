# VPN

`/vpn.html`. WireGuard access for devices that dial in to the NAS.

## Status card

Shows whether WireGuard is **running** or **stopped**, plus Start,
**Restart**, and **Stop**. When stopped, nothing on this box accepts new
VPN connections; existing peers cannot reconnect until you press Start.

## Server endpoint

What devices dial from outside: public IP or hostname. If the box cannot
reach the internet, it falls back to the LAN address and shows a warning to
replace it with your public IP/hostname before devices can connect.

**Save** stores the endpoint.

## Devices

Each row: name, VPN IP, status, last handshake, data transferred, remote
endpoint. A device shows *Online* only after its first handshake — no
handshake means packets are not reaching the server: check the endpoint
above and that your router forwards UDP to this box.

**Add device** (top right) mints a new private/public key pair,
generates a config file and QR code you can scan from a phone, and adds the
peer to WireGuard.

## Diagnostics

Interface up/down, listen port (e.g. 51820/udp), endpoint configured or
not, IP forwarding on/off, and which NIC carries internet traffic.

## Verified

- A `vpn stop` and start/restart cycle appear in the Activity Log
  (`vpn.stop`, and start/restart audit entries).
- Endpoint falls back to `10.0.0.69` with the warning shown, as expected
  when the VM has no public IP.
