# Pwnagotchi for PC (Linux x86_64 / Kali)

A standalone wrapper, hardware auditor, and automated patchset for running **Jayofelony Pwnagotchi** natively on standard Linux PCs (Kali, Debian, Ubuntu x86_64) with **zero Raspberry Pi hardware dependencies**.

---

## ✨ Features

- **Zero Pi Dependencies**: Bypasses all Raspberry Pi-exclusive hardware wheels (`gpiozero`, `inky`, `rpi-lgpio`, `rpi_hardware_pwm`, `smbus`, `pisugar`).
- **Hardware Doctor (`doctor.py`)**:
  - Automatically identifies Wi-Fi chipsets and tests nl80211 monitor mode capability.
  - Detects packet injection / frame deauthentication capabilities.
  - **Auto Passive Fallback**: If the wireless chipset lacks raw frame injection (e.g. onboard Realtek `rtw89`/`rtw88` or Intel `iwlwifi`), it automatically configures `personality.deauth = false` and `associate = false`. The agent operates smoothly as a **100% Passive Sniffer** (capturing handshakes and PMKIDs organically from client reconnects) without crashing.
- **Embedded Pwngrid Mock**: Replaces the external Go `pwngrid` binary with a built-in Python mock HTTP service on `127.0.0.1:8666`.
- **Anti-Reboot Safeguard**: Pins `main.name` to the host's actual hostname, neutralizing upstream logic that attempts to reboot non-Pi systems.
- **Clean Network Lifecycle**: Handles NetworkManager unmanagement, monitor VIF creation, Bettercap REST API initialization, and automatically restores all network interfaces upon exit (`Ctrl+C`).
- **Web UI**: Access the classic dynamic face and telemetry dashboard at `http://localhost:8080`.

---

## 🚀 One-Line Installation (Kali Linux Live / Debian)

After booting into Kali Linux, run the following single-line command:

```bash
sudo apt update && sudo apt install -y git bettercap libpcap-dev python3-pip python3-prctl iw aircrack-ng python3-dbus python3-pil fonts-dejavu openssh-client net-tools && git clone https://github.com/ShiTmoZ/pw-mini.git && cd pw-mini && sudo bash setup.sh
```

---

## 🎮 Running Pwnagotchi

Launch the automated runner:

```bash
sudo ./start.sh
```

### Options & Flags

- **Select specific Wi-Fi adapter**:
  ```bash
  sudo PWN_IFACE=wlan1 ./start.sh
  ```
- **Active injection probe (`aireplay-ng`)**:
  ```bash
  sudo PWN_DEEP_SCAN=1 ./start.sh
  ```

---

## 🌐 Web Dashboard

Once started, open your browser and navigate to:
- **URL**: `http://localhost:8080`
- **Default Username**: `admin`
- **Default Password**: `admin`

Handshake captures (`.pcapng`) are automatically saved to `/root/handshakes/`.

---

## 🛑 Stopping & Network Recovery

Press `Ctrl+C` in the terminal. `start.sh` automatically kills helper daemons, removes the temporary monitor interface, and restores NetworkManager.
