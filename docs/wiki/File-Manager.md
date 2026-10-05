# File Manager

`/files.html`. Browse, upload, and manage files under the ForgeOS storage
roots (the directories where pools mount, e.g. `/srv/nas`).

## Left column — storage roots

Click **nas** (or another root) to browse it. Folders like `music`,
`photos`, and `tank` are subdirectories. Clicking a folder opens it.

## Toolbar buttons

- **New folder** — creates a folder in the current directory.
- **Cut / Copy / Paste** — move or duplicate within the file system. Cut is
  enabled only after selecting a row.
- **Rename** — rename the selected row.
- **Permissions** — chmod/chown dialog for the selected row (owner:group and
  octal mode).
- **Download** — downloads the selected file.
- **Upload** — the blue **Upload** button at top right uploads files into
  the current directory. You can also drag files onto the table and drop.
- **Delete** — deletes the selected row (confirm dialog).

## Table columns

Checkbox, name, size, modified, permissions (octal, e.g. `drwxr-xr-x`),
owner.

## Breadcrumbs

The crumb trail above the table (`nas / music`) lets you jump up a level.

## Verified

- Browsing `/srv/nas/tank` shows the `music`, `photos`, `tank` directories
  and `INSTRUCTIONS.md` with owner/permissions.
- All file actions are logged — `files.chown`, `files.chmod` entries appear
  in the Activity Log.
