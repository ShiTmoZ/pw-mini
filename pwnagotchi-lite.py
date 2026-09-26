#!/usr/bin/env python3
"""
Pwnagotchi-Lite — minimal terminal handshake hunter.
===================================================
Single-file, zero-BS. Works on Kali Linux (and any Linux with bettercap).
Passive mode by default (no deauth — safe for rtw89 / no-dongle).

Usage:
  # 1. Start bettercap FIRST (separate terminal):
  sudo bettercap -iface wlan0

  # 2. In bettercap shell:
  > set api.rest.username pwnagotchi
  > set api.rest.password pwnagotchi
  > api.rest on
  > wifi.recon on

  # 3. Run Pwnagotchi-Lite:
  sudo ./pwnagotchi-lite.py

  # Or quick-start (auto-launches bettercap):
  sudo ./pwnagotchi-lite.py --auto

  # Passive mode (default, no deauth):
  sudo ./pwnagotchi-lite.py

  # Active mode (needs injection-capable HW like Atheros/RTL8811AU):
  sudo ./pwnagotchi-lite.py --active

Author: Hermes + DeepSeek V4 Flash
License: GPL3
"""

import argparse
import base64
import curses
import glob
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

# ─── BANNER ───────────────────────────────────────────────────────────────────

BANNER = r"""
  ____                    _              _   _   _ _   _
 |  _ \__      ____ _ ___| |__   ___    | |_| |_(_) |_| |
 | |_) \ \ /\ / / _` / __| '_ \ / _ \   | __| __| | __| |
 |  __/ \ V  V / (_| \__ \ | | | (_) |  | |_| |_| | |_|_|
 |_|     \_/\_/ \__,_|___/_| |_|\___/    \__|\__|_|\__(_)
"""

# ─── DEFAULTS ────────────────────────────────────────────────────────────────

DEFAULTS = {
    "iface": "wlan0",
    "bc_host": "127.0.0.1",
    "bc_port": 8081,
    "bc_user": "pwnagotchi",
    "bc_pass": "pwnagotchi",
    "recon_time": 15,
    "hop_time": 5,
    "channels": [],              # [] = all; [1,6,11] = 2.4GHz only
    "whitelist": [],
    "hs_dir": "/root/handshakes",
    "log_file": "pwnagotchi-lite.log",
    "passive": True,             # no deauth/assoc
    "auto_bc": False,            # auto-start bettercap
}

# ─── REST CLIENT ──────────────────────────────────────────────────────────────

class BCClient:
    """Minimal Bettercap REST API client."""

    def __init__(self, host, port, user, pwd):
        self._url = f"http://{host}:{port}/api"
        token = base64.b64encode(f"{user}:{pwd}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }

    def _req(self, method, path, body=None):
        data = json.dumps(body).encode() if body else None
        req = urllib.request.Request(self._url + path, data=data, method=method)
        for k, v in self._headers.items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"BC {e.code}: {e.read().decode()[:200]}")
        except (ConnectionRefusedError, TimeoutError) as e:
            raise RuntimeError(f"BC unreachable: {e}")

    def session(self):
        return self._req("GET", "/session")

    def run(self, cmd):
        return self._req("POST", "/session", {"cmd": cmd})

    def wait(self, retries=30, delay=1):
        for i in range(retries):
            try:
                r = self._req("GET", "/session")
                if "wifi" in r or "interfaces" in r:
                    return
            except Exception:
                pass
            time.sleep(delay)
        raise RuntimeError("Bettercap API not ready after 30s")

# ─── WIFI HELPERS ─────────────────────────────────────────────────────────────

def iface_channels(iface):
    """Return list of supported channels for an interface."""
    try:
        r = subprocess.run(
            ["iw", "dev", iface, "info"],
            capture_output=True, text=True, timeout=5
        )
        # Try to get channel list from iw list
        r2 = subprocess.run(
            ["iw", "list"],
            capture_output=True, text=True, timeout=5
        )
        channels = []
        in_band = False
        for line in r2.stdout.split("\n"):
            if "Band" in line and "GHz" in line:
                in_band = True
            if "MHz" in line and in_band and "[" in line:
                # Parse " * 2412 MHz [1] (20.0 dBm)"
                import re
                m = re.search(r'\[(\d+)\]', line)
                if m:
                    channels.append(int(m.group(1)))
            if "Band" in line and in_band and channels:
                # Next band started
                break
        return channels or list(range(1, 14))
    except Exception:
        return list(range(1, 14))

def ensure_bettercap(logger=None):
    """Install bettercap if missing."""
    def log(m):
        if logger: logger(m)
    r = subprocess.run(["which", "bettercap"], capture_output=True, timeout=5)
    if r.returncode == 0:
        return True
    log("bettercap not found — installing...")
    r = subprocess.run(["sudo", "apt", "install", "-y", "bettercap"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode == 0:
        log("bettercap installed")
        return True
    log(f"FAILED to install bettercap: {r.stderr[-200:]}")
    return False

def setup_monitor(iface, logger=None):
    """Put interface in monitor mode. Tries iw then airmon-ng."""
    def log(m):
        if logger:
            logger(m)

    log(f"Setting {iface} to monitor mode...")

    # Kill interfering processes first
    subprocess.run(["airmon-ng", "check", "kill"], capture_output=True, timeout=10)
    time.sleep(1)

    # Method 1: iw
    subprocess.run(["ip", "link", "set", iface, "down"], capture_output=True, timeout=5)
    r = subprocess.run(["iw", "dev", iface, "set", "type", "monitor"],
                       capture_output=True, text=True, timeout=5)
    subprocess.run(["ip", "link", "set", iface, "up"], capture_output=True, timeout=5)

    # Verify with iw
    r = subprocess.run(["iw", "dev", iface, "info"], capture_output=True, text=True, timeout=5)
    if "type monitor" in r.stdout:
        log("Monitor mode active (iw)")
        return True

    # Method 2: airmon-ng (creates wlan0mon)
    log("iw failed — trying airmon-ng...")
    r = subprocess.run(["airmon-ng", "start", iface],
                       capture_output=True, text=True, timeout=15)
    # airmon might rename to wlan0mon — check both
    mon = iface + "mon"
    for name in (iface, mon):
        r2 = subprocess.run(["iw", "dev", name, "info"],
                           capture_output=True, text=True, timeout=5)
        if "type monitor" in r2.stdout:
            log(f"Monitor mode active (airmon-ng → {name})")
            return True

    # Verify with tcpdump (final check)
    r3 = subprocess.run(
        ["tcpdump", "-i", iface, "-c", "1", "-t", "-v"],
        capture_output=True, text=True, timeout=5
    )
    if "IEEE" in r3.stderr or "WLAN" in r3.stderr or "802.11" in r3.stderr:
        log("Monitor mode active (tcpdump confirms 802.11)")
        return True

    log(f"FAILED: {iface} reject monitor mode")
    return False

def teardown_monitor(iface):
    """Restore managed mode."""
    subprocess.run(["ip", "link", "set", iface, "down"], capture_output=True, timeout=5)
    subprocess.run(["iw", "dev", iface, "set", "type", "managed"], capture_output=True, timeout=5)
    subprocess.run(["ip", "link", "set", iface, "up"], capture_output=True, timeout=5)
    subprocess.run(["nmcli", "dev", "set", iface, "managed", "yes"],
                   capture_output=True, timeout=5)
    subprocess.run(["systemctl", "restart", "NetworkManager"],
                   capture_output=True, timeout=10)

def start_bettercap(iface, port, user, pwd, bc_bin="bettercap"):
    """Launch bettercap in background."""
    eval_str = (
        f"set api.rest.address 0.0.0.0; "
        f"set api.rest.port {port}; "
        f"set api.rest.username {user}; "
        f"set api.rest.password {pwd}; "
        f"set api.rest.websocket true; "
        f"api.rest on"
    )
    proc = subprocess.Popen(
        [bc_bin, "-no-colors", "-eval", eval_str, "-iface", iface],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL
    )
    return proc

# ─── AGENT ────────────────────────────────────────────────────────────────────

class Agent:
    """Pwnagotchi-Lite core engine."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.bc = BCClient(cfg["bc_host"], cfg["bc_port"],
                           cfg["bc_user"], cfg["bc_pass"])
        self._start = time.time()
        self._hs_seen = set()
        self._bc_proc = None

        # State for UI
        self.state = {
            "aps": [],
            "tot_aps": 0,
            "tot_clients": 0,
            "channel": "?",
            "hs_count": 0,
            "last_hs": None,
            "epoch": 0,
            "running": False,
            "uptime": "00:00",
            "passive": cfg["passive"],
            "iface": cfg["iface"],
            "logs": [],
        }

        os.makedirs(cfg["hs_dir"], exist_ok=True)

    def log(self, msg):
        logging.info(msg)
        self.state["logs"].append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        self.state["logs"] = self.state["logs"][-100:]

    def poll_handshakes(self):
        """Scan hs_dir for new .pcapng files."""
        pattern = os.path.join(self.cfg["hs_dir"], "*.pcap*")
        for f in sorted(glob.glob(pattern)):
            if f not in self._hs_seen:
                self._hs_seen.add(f)
                self.state["hs_count"] += 1
                self.state["last_hs"] = os.path.basename(f)
                size = os.path.getsize(f)
                self.log(f" [+] Handshake: {os.path.basename(f)} ({size} bytes)")

    def filter_aps(self, raw_aps):
        """Filter: skip OPEN, skip whitelist, skip unsupported channels."""
        supported = iface_channels(self.cfg["iface"])
        whitelist = self.cfg["whitelist"]
        out = []
        for ap in raw_aps:
            enc = ap.get("encryption", "")
            mac = ap.get("mac", "").lower()
            hostname = ap.get("hostname", "")
            ch = ap.get("channel", 0)
            if enc == "" or enc == "OPEN":
                continue
            if mac in whitelist or mac[:13] in whitelist or hostname in whitelist:
                continue
            if ch and supported and ch not in supported:
                continue
            out.append(ap)
        out.sort(key=lambda a: (-len(a.get("clients", [])), a.get("rssi", 0)))
        return out

    def epoch(self):
        """Single operational cycle."""
        self.state["epoch"] += 1
        ep = self.state["epoch"]

        # ── RECON ──
        recon_t = self.cfg["recon_time"]
        self.state["channel"] = "*"
        self.log(f"[{ep}] RECON ({recon_t}s)")
        try:
            if self.cfg["channels"]:
                spec = ",".join(str(c) for c in self.cfg["channels"])
                self.bc.run(f"wifi.recon.channel {spec}")
            else:
                self.bc.run("wifi.recon.channel clear")
        except Exception as e:
            self.log(f"  RECON error: {e}")
            return

        time.sleep(recon_t)

        # ── COLLECT ──
        try:
            sess = self.bc.session()
        except Exception as e:
            self.log(f"  Session error: {e}")
            return

        raw_aps = sess.get("wifi", {}).get("aps", [])
        aps = self.filter_aps(raw_aps)
        self.state["aps"] = aps
        self.state["tot_aps"] = len(aps)
        self.state["tot_clients"] = sum(len(ap.get("clients", [])) for ap in aps)
        self.log(f"  APs: {len(aps)} | Clients: {self.state['tot_clients']}")

        if aps:
            best = aps[0]
            self.state["channel"] = str(best.get("channel", "?"))
            top = ", ".join(
                f"{a['hostname'][:16]}({len(a.get('clients',[]))})"
                for a in aps[:5]
            )
            self.log(f"  Top: {top}")
        else:
            self.state["channel"] = "-"

        # ── PASSIVE / ACTIVE ──
        # In passive mode: just wait and listen
        # In active mode: assoc + deauth per AP/client
        # (stub for now — active mode needs injection-capable HW)
        if not self.cfg["passive"] and aps:
            self.log("  Active mode is a stub — add deauth/assoc loop here")

        # ── HANDSHAKES ──
        self.poll_handshakes()

        # ── HOP ──
        if aps:
            wait = self.cfg["hop_time"]
        else:
            wait = self.cfg["hop_time"] // 3 or 2
        time.sleep(wait)

        self.state["uptime"] = self._fmt_uptime(time.time() - self._start)

    def _fmt_uptime(self, secs):
        m, s = divmod(int(secs), 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def run(self, stdscr):
        """Curses-driven main loop."""
        curses.curs_set(0)
        curses.init_pair(1, curses.COLOR_RED, 0)
        curses.init_pair(2, curses.COLOR_GREEN, 0)
        curses.init_pair(3, curses.COLOR_CYAN, 0)
        curses.init_pair(4, curses.COLOR_YELLOW, 0)
        curses.init_pair(5, curses.COLOR_MAGENTA, 0)

        self.state["running"] = True
        self.log(BANNER)
        self.log(f"Interface: {self.cfg['iface']} | Mode: {'PASSIVE' if self.cfg['passive'] else 'ACTIVE'}")
        self.log(f"Handshakes → {self.cfg['hs_dir']}")

        # Wait for Bettercap
        if self.cfg["auto_bc"]:
            # Install bettercap if missing
            self.log("Checking bettercap...")
            ensure_bettercap(self.log)

            # Setup monitor mode
            if not setup_monitor(self.cfg["iface"], self.log):
                self.log("FATAL: Cannot enable monitor mode")
                self.log("Try manually: sudo airmon-ng check kill && sudo iw dev wlan0 set type monitor")
                self.state["running"] = False
                self._draw(stdscr)
                stdscr.getch()
                return

            self.log("Starting bettercap...")
            self._bc_proc = start_bettercap(
                self.cfg["iface"], self.cfg["bc_port"],
                self.cfg["bc_user"], self.cfg["bc_pass"]
            )
            time.sleep(3)

        self.log("Connecting to Bettercap API...")
        try:
            self.bc.wait()
        except RuntimeError as e:
            self.log(f"FAILED: {e}")
            self.log("Make sure bettercap is running with api.rest enabled")
            self.state["running"] = False
            self._draw(stdscr)
            stdscr.getch()
            return

        self.log("Connected")

        # Configure wifi module
        try:
            self.bc.run(f"set wifi.interface {self.cfg['iface']}")
            self.bc.run(f"set wifi.handshakes.file {self.cfg['hs_dir']}")
            self.bc.run("set wifi.handshakes.aggregate false")
            self.bc.run("wifi.recon on")
            self.log("WiFi recon started")
        except Exception as e:
            self.log(f"BC config error: {e}")

        # Main epoch loop
        stdscr.nodelay(True)
        while self.state["running"]:
            try:
                self.epoch()
            except Exception as e:
                self.log(f"Epoch error: {e}")
                time.sleep(3)

            self._draw(stdscr)

            try:
                k = stdscr.getch()
                if k == ord('q'):
                    break
                elif k == ord('r'):
                    self.log("Manual epoch")
                elif k == ord(' '):
                    self.log("Pause — press any key")
                    stdscr.nodelay(False)
                    stdscr.getch()
                    stdscr.nodelay(True)
            except:
                pass

        self.state["running"] = False
        self._draw(stdscr)
        self.log("Shutdown")

        if self._bc_proc:
            self._bc_proc.terminate()

    def _draw(self, stdscr):
        h, w = stdscr.getmaxyx()
        s = self.state
        stdscr.clear()

        # Title bar
        title = f" Pwnagotchi-Lite  |  {s['iface']}  |  Uptime: {s['uptime']} "
        stdscr.attron(curses.A_BOLD | curses.color_pair(2))
        stdscr.addstr(0, 0, title.ljust(w - 1)[:w])
        stdscr.attroff(curses.A_BOLD | curses.color_pair(2))

        # Status
        mode_str = "PASSIVE" if s["passive"] else "ACTIVE"
        mode_color = curses.color_pair(4) if s["passive"] else curses.color_pair(1)
        status = (
            f" [{mode_str}]  "
            f"APs: {s['tot_aps']}  "
            f"Clients: {s['tot_clients']}  "
            f"Chan: {s['channel']}  "
            f"Handshakes: {s['hs_count']}  "
            f"Epoch: {s['epoch']}"
        )
        stdscr.addstr(1, 0, status.ljust(w - 1)[:w], mode_color)

        # Last handshake
        if s["last_hs"]:
            stdscr.addstr(2, 0, f" Last HS: {s['last_hs']}", curses.color_pair(2))

        # AP list header
        ap_h = h - 7
        stdscr.addstr(4, 0, f" {'BSSID':<18} {'SSID':<22} {'CH':<4} {'CLIENTS':<8} {'RSSI':<6} {'ENC':<10}", curses.A_BOLD)

        aps = s.get("aps", [])
        if not aps:
            stdscr.addstr(5, 2, "(no access points found)" if s["running"] else "(idle)", curses.color_pair(4))
        else:
            for i, ap in enumerate(aps[:ap_h]):
                line = (
                    f" {ap.get('mac',''):<18} "
                    f"{ap.get('hostname','')[:22]:<22} "
                    f"{ap.get('channel','?'):<4} "
                    f"{len(ap.get('clients',[])):<8} "
                    f"{ap.get('rssi',0):<6} "
                    f"{ap.get('encryption','')[:10]:<10}"
                )
                color = curses.color_pair(2) if len(ap.get('clients', [])) > 0 else 0
                stdscr.addstr(5 + i, 0, line[:w], color)

        # Logs
        logs = s.get("logs", [])
        for i in range(min(len(logs), 3)):
            idx = len(logs) - 3 + i
            if idx >= 0:
                stdscr.addstr(h - 4 + i, 0, f" {logs[idx][:w-3]}", curses.color_pair(4))

        # Help
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(h - 1, 0, " [q]uit  [r]econ  [SPC]pause".ljust(w - 1)[:w])
        stdscr.attroff(curses.A_REVERSE)
        stdscr.refresh()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Pwnagotchi-Lite — terminal Wi-Fi handshake hunter",
        epilog="Example: sudo ./pwnagotchi-lite.py --iface wlan1 --active"
    )
    ap.add_argument("--iface", default=DEFAULTS["iface"])
    ap.add_argument("--active", action="store_true", help="Enable deauth/assoc (needs injection-capable HW)")
    ap.add_argument("--channels", help="Comma-separated: 1,6,11")
    ap.add_argument("--hs-dir", default=DEFAULTS["hs_dir"])
    ap.add_argument("--recon", type=int, default=DEFAULTS["recon_time"], help="Recon seconds per epoch")
    ap.add_argument("--auto", action="store_true", help="Auto-start bettercap")
    ap.add_argument("--log", default=DEFAULTS["log_file"])
    args = ap.parse_args()

    cfg = DEFAULTS.copy()
    cfg["iface"] = args.iface
    cfg["passive"] = not args.active
    cfg["recon_time"] = args.recon
    cfg["hs_dir"] = os.path.abspath(args.hs_dir)
    cfg["auto_bc"] = args.auto
    if args.channels:
        cfg["channels"] = [int(c.strip()) for c in args.channels.split(",")]
    if args.log:
        cfg["log_file"] = args.log

    logging.basicConfig(
        filename=cfg["log_file"],
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    agent = Agent(cfg)

    # Must run as root for monitor mode
    if os.geteuid() != 0 and cfg["auto_bc"]:
        print("⚠  --auto needs root (sudo)")
        sys.exit(1)

    try:
        curses.wrapper(agent.run)
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()