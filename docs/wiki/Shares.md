# Shares (SMB)

`/shares.html`. Folders on the NAS shared over SMB to Windows, macOS, and
Linux.

## Creating a share

1. Click **New Share** (top right).
2. Pick the folder to share (the share dialog lists directories under the
   storage roots).
3. Give it a name and choose which users may read and which may write.
4. Save. ForgeOS regenerates the loudest possible samba config — don't edit
   it by hand; the next save overwrites it.

Under the hood: `smb.conf` is written and `smbd`/`nmbd` reload. Clients
connect with `\\<nas-ip>\<share-name>`.

## Active connections

Live `smbstatus` output: which users are connected, from which machine, and
which protocol/encryption level is in use.

## Raw configuration

`smb.conf` source kept for reference. Verbatim edits made through the
*Advanced* text area are preserved — ForgeOS only manages its own
`include` file.

## Verified

- Empty state renders ("No shares yet").
- Saving a share regenerates config and `smbd` reloads; tested in the audit:
  `service.start smb` appears in the log.
