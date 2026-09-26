# Pwnagotchi-Lite
**Terminal-based Wi-Fi handshake hunter. Minimal, no-BS, no Pi dependencies.**

## Philosophy

Pwnagotchi original is designed for Raspberry Pi + E-Ink display + deauth.
Pwnagotchi-Lite is designed for **PC + terminal + any WiFi card**.

| Feature | Original | Lite |
|---------|----------|------|
| Display | E-Ink (inky/epd) | curses terminal |
| Web UI | Flask | ✗ |
| Bluetooth | ✓ | ✗ |
| Mesh/Pwngrid | ✓ | ✗ |
| AI (removed) | ✗ now | planned as advice layer |
| Deauth/Assoc | ✓ | optional (`--active`) |
| Pi-only display deps | ✓ | ✗ |
| Single-file deploy | ✗ | ✓ |

## How it works (for passive mode)

```
┌─────────────┐     REST API     ┌──────────────┐
│ bettercap   │ ◄──────────────► │ pwnagotchi-  │
│ (wifi.recon)│                  │ lite.py      │
│             │                  │              │
│ session() ──┼─── AP list ────► │ epoch loop   │
│ events()  ──┼─── HS notif ──► │ curses UI    │
└─────────────┘                  └──────┬───────┘
                                        │
                                   ┌────▼──────┐
                                   │ handshakes │
                                   │ .pcapng   │
                                   └───────────┘
```

## Requirements

- **OS**: Linux (Kali recommended, any distro with iw + nmcli works)
- **Bettercap**: `sudo apt install bettercap`
- **Python**: 3.8+ (stdlib only — no pip install needed)

## Quick start

### 1. Set up monitor mode manually (or use --auto)

```bash
sudo nmcli dev set wlan0 managed no
sudo ip link set wlan0 down
sudo iw dev wlan0 set type monitor
sudo ip link set wlan0 up
```

### 2. Start bettercap

```bash
sudo bettercap -iface wlan0
```

In bettercap shell:
```
set api.rest.username pwnagotchi
set api.rest.password pwnagotchi
api.rest on
wifi.recon on
```

### 3. Run Pwnagotchi-Lite

```bash
sudo ./pwnagotchi-lite.py
```

Or with one command:
```bash
sudo ./pwnagotchi-lite.py --auto
```

### Restore network after use

```bash
sudo nmcli dev set wlan0 managed yes
sudo ip link set wlan0 down
sudo iw dev wlan0 set type managed
sudo ip link set wlan0 up
sudo systemctl restart NetworkManager
```

## Advanced usage

```bash
# Scan only 2.4GHz channels 1,6,11
sudo ./pwnagotchi-lite.py --channels 1,6,11

# Custom handshake directory
sudo ./pwnagotchi-lite.py --hs-dir /root/pcaps

# Faster recon (10s per epoch)
sudo ./pwnagotchi-lite.py --recon 10

# Active mode (deauth + assoc — needs dongle with injection)
sudo ./pwnagotchi-lite.py --active

# Different interface
sudo ./pwnagotchi-lite.py --iface wlan1
```

## Test with your D-Link

1. Plug D-Link to power (no ethernet needed)
2. Your PC scans and sees it in AP list
3. Turn D-Link off/on → clients reconnect → handshake captured
4. Check `ls -la /root/handshakes/` for .pcapng files

## Convert & crack

```bash
sudo apt install hcxtools
hcxpcapngtool -o capture.hc22000 /root/handshakes/*.pcapng
hashcat -m 22000 capture.hc22000 /usr/share/wordlists/rockyou.txt
```