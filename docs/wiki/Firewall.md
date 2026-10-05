# Firewall

`/firewall.html`. Uncomplicated Firewall (ufw) managed from the UI.

## Master switch

The big green switch toggles the whole firewall on or off. The card says
how many rules are active.

## Default policy

What traffic with no matching rule is allowed to do:
- **Incoming** — default **Deny**. Every service on the NAS such as SMB,
  the web UI, or SSH must have an explicit rule.
- **Outgoing** — default **Allow**.

## Active rules

Rules evaluate top to bottom. Each row shows action, port, and protocol;
the trash icon deletes it. **Add Rule** opens the dialog — choose service
or port, allow/deny, and source restrictions.

## Verified

- Default policies: incoming deny, outgoing allow.
- A rule toggle logs `firewall.toggle` in the Activity Log.
