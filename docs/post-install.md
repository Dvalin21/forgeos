# ForgeOS Post-Install Checklist

Complete these steps after the installer finishes.

---

## 1. Change the Default Admin Password

The installer generates a random password and prints it in the summary. Log into the Web UI immediately and change it.

**Web UI:** Settings → Security → Change Password  
**CLI:**
```bash
forgeos-ctl open   # prints URL and default credentials
```

---

## 2. Set Up DNS / Domain

If using a real domain (not `nas.local`):

- Point an A record at your server's public IP
- Run `forgeos-nginx certbot --domain your.domain --email you@domain.com`
- Or let the installer handle it if `ACME_EMAIL` was set

For LAN-only access, `hostname.local` works out of the box via mDNS.

---

## 3. Configure Drives

If you have additional data drives:

```bash
forgeos-drives list              # See all detected drives with types
forgeos-storage create-pool      # Interactive pool creation wizard

# Optional: add an SSD/NVMe cache in front of an HDD pool
forgeos-cache setup /dev/nvme0n1 /dev/md0 writeback
```

---

## 4. Create SMB Users

```bash
forgeos-samba add-user username password
```

Or via **Web UI:** Network → File Sharing → SMB → Users

---

## 5. Configure Backups

```bash
# Test local backup works
forgeos-backup run

# Add a cloud backend (Backblaze B2 is cheapest)
forgeos-cloud add-b2

# Verify cloud sync
forgeos-cloud test
```

Save `/etc/forgeos/backup/keys/master.key` to a secure offline location. Without it, encrypted backups cannot be restored.

---

## 6. Configure Mail DNS (if mail module installed)

```bash
forgeos-mail dns-records   # Prints exact DNS records to add
```

Add all five records (A, MX, SPF, DKIM, DMARC) before sending external mail.

---

## 7. Coral TPU (if installed)

```bash
forgeos-coral status       # Check if /dev/apex_* appeared
```

If no devices show: reboot first (DKMS kernel module was just built). If still missing after reboot:

```bash
forgeos-coral fix-aspm     # Adds pcie_aspm=off to GRUB
# reboot again
```

Then configure cameras in `/srv/forgeos/frigate/config/config.yml` and start Frigate:

```bash
forgeos-coral frigate-start
```

---

## 8. Run the Test Suite

```bash
sudo bash test-forgeos.sh
```

All tests should pass except anything marked SKIP (hardware not present) or WARN (optional services).
