# Google Coral TPU — ForgeOS Reference

## Supported Hardware

| Device | PCI ID | Devices Created |
|---|---|---|
| Coral M.2 Accelerator (single) | 1ac1:089a | `/dev/apex_0` |
| Coral PCIe Accelerator (single) | 1ac1:089a | `/dev/apex_0` |
| Coral M.2 Accelerator with Dual Edge TPU | 1ac1:089a × 2 | `/dev/apex_0` + `/dev/apex_1` |

## Driver Notes

The official `gasket-dkms` package from Google's apt repo (`packages.cloud.google.com`) **does not build on Linux kernel 6.x+**. ForgeOS uses the [KyleGospo/gasket-dkms](https://github.com/KyleGospo/gasket-dkms) community fork, which contains the required compatibility patches.

The runtime library (`libedgetpu1-std`) is still installed from Google's repo — only the DKMS kernel module package is replaced.

## Dual TPU Requirements

The Dual Edge TPU card has an internal PCIe switch that exposes two independent PCIe functions. For both to be enumerated:

- The M.2 slot **must support x2 PCIe lane bifurcation**
- If the slot is x1 only, only `/dev/apex_0` will appear regardless of the card

Check bifurcation support in your motherboard's BIOS under PCIe/M.2 settings.

## MSI-X Requirement

All Coral PCIe devices require **MSI-X** interrupt support from the host PCIe slot. Check:

```bash
lspci -vv | grep -A5 "089a" | grep "MSI-X"
```

If nothing appears, the apex driver will not create `/dev/apex_*`. This is a hardware limitation. Some boards require BIOS updates to expose MSI-X on M.2 slots.

## Troubleshooting

### `/dev/apex_*` missing after reboot

```bash
forgeos-coral status      # Check module load status
lsmod | grep apex         # Is module loaded?
lspci -nn | grep 089a     # Is hardware visible to kernel?
```

**Fix 1: ASPM interference**
```bash
forgeos-coral fix-aspm    # Adds pcie_aspm=off to GRUB
sudo reboot
```

**Fix 2: Rebuild driver for current kernel**
```bash
forgeos-coral rebuild-driver
sudo reboot
```

**Fix 3: Manual module load**
```bash
sudo modprobe gasket
sudo modprobe apex
ls /dev/apex_*
```

### Permission denied accessing `/dev/apex_0`

```bash
sudo usermod -aG apex $USER
# log out and back in
```

### Temperature monitoring

```bash
forgeos-coral temp
# or directly:
cat /sys/class/apex/apex_0/temp   # returns millidegrees, divide by 1000
```

## Frigate NVR

After Coral is working:

```bash
forgeos-coral frigate-start

# Edit camera config
forgeos-coral frigate-config
# Adds cameras to /srv/forgeos/frigate/config/config.yml

# Watch logs
forgeos-coral frigate-logs
```

Web UI: `https://nvr.your-domain`

## Performance

| Mode | Speed | Temperature |
|---|---|---|
| `libedgetpu1-std` (default) | ~110 TOPS | ~50–60°C |
| `libedgetpu1-max` | ~125 TOPS | ~70–80°C |

Switch to max clock (requires reinstall of runtime):
```bash
sudo apt install libedgetpu1-max
```

Only use max clock if your enclosure has adequate airflow.
