#!/usr/bin/env python3
"""
doctor.py -- Pwnagotchi Hardware Auditor & config generator for PC / Linux (x86_64).

It scans the local Wi-Fi interfaces with `iw`, checks whether monitor mode and
raw frame injection (deauthentication) are supported, and then writes a minimal
`/etc/pwnagotchi/config.toml` that complements (never replaces) upstream's
`defaults.toml`:

  * injection works        -> ACTIVE  mode  (personality.deauth = true)
  * injection unavailable  -> PASSIVE mode  (personality.deauth = false)
    so Pwnagotchi keeps capturing handshakes / PMKIDs passively and never tries
    to transmit 802.11 frames (no crashes on Realtek rtw89 / Intel iwlwifi).

By default the card is only *inspected* (NetworkManager keeps owning it, no
interface is changed).  Pass `--deep-scan` to additionally run a live
`aireplay-ng --test` injection probe on a temporary monitor interface.

Outputs:
  * <config-out>  (default /etc/pwnagotchi/config.toml)  -- TOML user config
  * <state-out>   (default /etc/pwnagotchi/doctor.json)  -- machine readable
                                                           summary for start.sh
Exit codes: 0 = ok, 2 = no usable Wi-Fi interface, 3 = write error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_CONFIG = "/etc/pwnagotchi/config.toml"
DEFAULT_STATE = "/etc/pwnagotchi/doctor.json"
MAX_IFACE_LEN = 15  # IFNAMSIZ - 1

# Drivers that physically cannot inject raw 802.11 frames with their in-kernel
# driver.  This is the "warn the user" list from the spec (rtw89 / iwlwifi) plus
# other common unsupported parts seen on laptops and SBCs.
NO_INJECTION_DRIVERS = {
    "iwlwifi", "iwlmvm", "iwlwifi_pci",
    "rtw89", "rtw89_8852ae", "rtw89_8852be", "rtw89_8852ce", "rtw89_8851be",
    "rtw88", "rtw88_8821ce", "rtw88_8822ce", "rtw88_8822be", "rtw88_8723de",
    "brcmfmac", "brcmfmac_sdio",
    "rtl8xxxu", "rtl8188eu", "r8188eu",
    "mt7601u", "mt7663u",
    "ath6kl", "ath6kl_sdio",
}

# Drivers that are well known in the wardriving community to support monitor
# mode *and* frame injection with their in-kernel driver.
KNOWN_INJECTION_DRIVERS = {
    "rt2800usb", "rt2870", "rt73usb", "rt2500usb", "rt2x00usb", "rt2x00pci",
    "rtl8187", "rtl8192cu",
    "rtl8812au", "rtl8821au", "rtl8814au", "rtl88xxau", "88XXau", "8821au",
    "ath9k", "ath9k_htc", "ath9k_common", "ath9k_hw", "carl9170",
    "mt76", "mt76x0u", "mt76x2u", "mt7921u", "mt7921e", "mt7612u", "mt7610u",
    "p54usb", "p54pci", "cw1200", "b43", "b43legacy",
}

# ANSI helpers (silently disabled when not talking to a tty).
_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if _TTY else text


def info(msg: str) -> None:
    print("%s %s" % (_c("1;34", "[doctor]"), msg))


def ok(msg: str) -> None:
    print("%s %s" % (_c("1;32", "[  ok  ]"), msg))


def warn(msg: str) -> None:
    print("%s %s" % (_c("1;33", "[ warn ]"), msg))


def err(msg: str) -> None:
    print("%s %s" % (_c("1;31", "[ fail ]"), msg), file=sys.stderr)


def _run(argv, timeout=15):
    """Run a command, return (returncode, combined output). Never raises."""
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=timeout)
        return proc.returncode, proc.stdout
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)


def list_interfaces():
    """Parse `iw dev` into a list of {iface, phy, type, driver} dicts."""
    rc, out = _run(["iw", "dev"])
    if rc != 0 or not out:
        return []

    interfaces, current, phy = [], None, None
    for line in out.splitlines():
        m = re.match(r"^phy#(\d+)", line)
        if m:
            phy = "phy%s" % m.group(1)
            continue
        m = re.match(r"^\s*Interface\s+(\S+)", line)
        if m:
            current = {"iface": m.group(1), "phy": phy, "type": None, "driver": None}
            interfaces.append(current)
            continue
        m = re.match(r"^\s*type\s+(\S+)", line)
        if m and current is not None:
            current["type"] = m.group(1)

    for entry in interfaces:
        entry["driver"] = driver_of(entry["iface"])
    return interfaces


def driver_of(iface: str):
    """Return the kernel driver/module name bound to an interface, if known."""
    link = "/sys/class/net/%s/device/driver" % iface
    try:
        if os.path.islink(link):
            base = os.path.basename(os.path.realpath(link))
            return base or None
    except OSError:
        pass
    return None


def parse_phy_modes():
    """Parse `iw list` into {phy: set(supported interface modes)}."""
    rc, out = _run(["iw", "list"])
    if rc != 0 or not out:
        return {}

    modes, phy, in_modes = {}, None, False
    for line in out.splitlines():
        m = re.match(r"^Wiphy (phy\d+)", line)
        if m:
            phy = m.group(1)
            modes[phy] = set()
            in_modes = False
            continue
        if phy is None:
            continue
        if re.match(r"^\s*Supported interface modes:", line):
            in_modes = True
            continue
        if in_modes:
            m = re.match(r"^\s*\*\s+(\S+)", line)
            if m:
                modes[phy].add(m.group(1))
            elif line.strip() and not line.startswith("\t\t"):
                in_modes = False
    return modes


def monitor_name(base: str) -> str:
    """Derive a <=15 char monitor interface name from a base interface name."""
    if base.endswith("mon"):
        return base[:MAX_IFACE_LEN]
    return (base + "mon")[:MAX_IFACE_LEN]


def current_hostname() -> str:
    """
    Return this machine's hostname.

    pwnagotchi.set_name() compares config['main']['name'] with /etc/hostname
    and *rewrites /etc/hostname and reboots* when they differ.  On a PC wrapper
    we must therefore pin main.name to the existing hostname so set_name() is a
    no-op.  (If the hostname is not a valid pwnagotchi name, set_name() bails
    out with a warning before touching anything, which is equally safe.)
    """
    for path in ("/etc/hostname", "/proc/sys/kernel/hostname"):
        try:
            with open(path, "r") as fp:
                value = fp.read().strip()
            if value:
                return value
        except OSError:
            continue
    try:
        import socket
        return socket.gethostname()
    except Exception:
        return ""


def deep_injection_test(base_iface: str, phy):
    """
    Live probe: create a temporary monitor vif, run `aireplay-ng --test` and
    delete the vif again.  Returns (result, reason) where result is
    True / False / None (inconclusive).
    """
    if os.geteuid() != 0:
        return None, "live test needs root"
    if not shutil.which("aireplay-ng"):
        return None, "aireplay-ng not installed"

    test_iface = monitor_name("pwndoct")
    # make sure we do not clash with a leftover vif
    _run(["iw", "dev", test_iface, "del"])

    rc, out = _run(["iw", "dev", base_iface, "interface", "add", test_iface, "type", "monitor"])
    if rc != 0:
        return None, "could not create temporary monitor vif (%s)" % out.strip()

    try:
        _run(["ip", "link", "set", test_iface, "up"])
        rc, out = _run(["aireplay-ng", "--test", test_iface], timeout=25)
        low = out.lower()
        if "injection is working" in low:
            return True, "aireplay-ng reports injection is working"
        if "no answer" in low or "injection is not working" in low or "failed" in low:
            return False, "aireplay-ng reports no injection"
        return None, "aireplay-ng result inconclusive"
    finally:
        _run(["ip", "link", "set", test_iface, "down"])
        _run(["iw", "dev", test_iface, "del"])


def audit(forced_iface=None, deep=False):
    """
    Inspect the machine and return a report dict:

      {ok, error, base_iface, mon_iface, mode, injection, driver, phy,
       monitor, reason, interfaces: [...]}
    """
    interfaces = list_interfaces()
    if not interfaces:
        return {
            "ok": False,
            "error": "no wireless interfaces found (is this PC Wi-Fi capable?)",
            "interfaces": [],
        }

    phy_modes = parse_phy_modes()

    for entry in interfaces:
        entry["monitor"] = "monitor" in phy_modes.get(entry["phy"], set())
        driver = entry["driver"]
        if driver in NO_INJECTION_DRIVERS:
            entry["injection"] = False
            entry["reason"] = "driver '%s' cannot inject raw 802.11 frames" % driver
        elif driver in KNOWN_INJECTION_DRIVERS:
            entry["injection"] = True
            entry["reason"] = "driver '%s' is known to support frame injection" % driver
        elif driver is None:
            entry["injection"] = None
            entry["reason"] = "could not determine driver, assuming no injection"
        else:
            entry["injection"] = None
            entry["reason"] = "driver '%s' unknown, assuming no injection until proven" % driver

    # pick the interface to use
    chosen = None
    if forced_iface:
        chosen = next((i for i in interfaces if i["iface"] == forced_iface), None)
        if chosen is None:
            return {"ok": False, "error": "interface '%s' not found" % forced_iface,
                    "interfaces": interfaces}
        if not chosen["monitor"]:
            warn("interface '%s' does not advertise monitor mode in `iw list`" % forced_iface)
    else:
        monitor_capable = [i for i in interfaces if i["monitor"]]
        if not monitor_capable:
            return {"ok": False,
                    "error": "none of the Wi-Fi interfaces support monitor mode",
                    "interfaces": interfaces}
        # prefer one that can inject, then unknown, then definitely passive
        rank = {True: 0, None: 1, False: 2}
        monitor_capable.sort(key=lambda i: rank.get(i["injection"], 1))
        chosen = monitor_capable[0]

    # optional live probe (overrides the heuristic when conclusive)
    if deep:
        info("running live injection probe on %s ..." % chosen["iface"])
        result, reason = deep_injection_test(chosen["iface"], chosen["phy"])
        chosen["reason"] = reason
        if result is not None:
            chosen["injection"] = result

    injection = chosen["injection"] is True
    mon_iface = monitor_name(chosen["iface"])

    return {
        "ok": True,
        "base_iface": chosen["iface"],
        "mon_iface": mon_iface,
        "phy": chosen["phy"],
        "driver": chosen["driver"],
        "monitor": chosen["monitor"],
        "injection": injection,
        "injection_known": chosen["injection"],
        "reason": chosen["reason"],
        "mode": "active" if injection else "passive",
        "interfaces": interfaces,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


CONFIG_TEMPLATE = """\
# Auto-generated by doctor.py -- do NOT hand-edit unless you know what you do.
# It is merged *on top of* upstream's defaults.toml by pwnagotchi (user config
# always wins), so only the PC-specific overrides live here.

[main]
# name is pinned to this PC's existing hostname: pwnagotchi.set_name() rewrites
# /etc/hostname *and reboots* when the two differ, which we never want here.
name = "{name}"
iface = "{mon_iface}"
# start.sh creates the monitor interface before pwnagotchi starts, so there is
# no on-device monstart helper to call.
mon_start_cmd = ""
no_restart = true

[main.log]
path = "{log_dir}/pwnagotchi.log"
path-debug = "{log_dir}/pwnagotchi-debug.log"

# Pi-only / interactive plugins are disabled for a headless PC install.
[main.plugins.auto-update]
enabled = false

[main.plugins.auto_backup]
enabled = false

[main.plugins.fix_services]
enabled = false

[main.plugins.gpio_buttons]
enabled = false

[personality]
# ACTIVE mode requires raw frame injection.  In PASSIVE mode deauth/associate
# stay false so Pwnagotchi only listens and captures handshakes + PMKIDs.
deauth = {deauth}
associate = {associate}
advertise = true
hop_recon_time = 5
min_recon_time = 5
recon_time = 10
recon_inactive_multiplier = 1

[bettercap]
hostname = "127.0.0.1"
scheme = "http"
port = 8081
username = "pwnagotchi"
password = "pwnagotchi"
handshakes = "{handshakes_dir}"

[ui]
invert = false
fps = 0.0

[ui.display]
enabled = false
type = "dummydisplay"

[ui.web]
enabled = true
address = "0.0.0.0"
port = 8080
auth = false

# zram/overlay mounts are a Pi thing; keep the host filesystem alone.
[fs.memory]
enabled = false
"""


def render_config(report, config_path):
    # TOML basic strings treat backslashes as escapes, so normalise any
    # platform-specific separators to forward slashes (a no-op on Linux).
    config_dir = os.path.dirname(os.path.abspath(config_path)).replace("\\", "/")
    active = report["mode"] == "active"
    # keep the hostname verbatim (minus TOML-unsafe characters) so upstream's
    # set_name() sees no change and never reboots the PC.
    name = current_hostname().replace("\\", "").replace('"', "")
    base = config_dir.rstrip("/")
    return CONFIG_TEMPLATE.format(
        name=name,
        mon_iface=report["mon_iface"],
        log_dir=base + "/log",
        handshakes_dir=base + "/handshakes",
        deauth="true" if active else "false",
        associate="true" if active else "false",
    )


def write_file(path, content, mode=0o644):
    directory = os.path.dirname(os.path.abspath(path))
    if directory and not os.path.isdir(directory):
        os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as fp:
        fp.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def print_summary(report):
    print()
    if not report.get("ok"):
        err(report.get("error", "unknown error"))
        for entry in report.get("interfaces", []):
            print("        - %s (phy=%s driver=%s monitor=%s)" % (
                entry.get("iface"), entry.get("phy"), entry.get("driver"), entry.get("monitor")))
        return

    info("interfaces found:")
    for entry in report["interfaces"]:
        marker = "*" if entry["iface"] == report["base_iface"] else " "
        print("        %s %-16s phy=%-6s driver=%-14s monitor=%-5s injection=%s" % (
            marker, entry["iface"], entry["phy"], entry["driver"],
            entry["monitor"], entry["injection"]))

    print()
    info("base interface    : %s (%s, driver=%s)" % (
        report["base_iface"], report["phy"], report["driver"]))
    info("monitor interface : %s" % report["mon_iface"])
    info("detection         : %s" % report["reason"])

    print()
    if report["injection"]:
        ok("packet injection / deauthentication IS supported -> FULL (active) mode")
        ok("personality.deauth = true, personality.associate = true")
    else:
        warn("packet injection / deauthentication is NOT supported on this card.")
        warn("Falling back to 100%% PASSIVE handshake + PMKID capture.")
        warn("personality.deauth = false, personality.associate = false")
        warn("Pwnagotchi will only listen; it will never try to transmit frames.")
    print()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="doctor.py",
        description="Audit PC Wi-Fi hardware and generate the pwnagotchi config.toml.")
    parser.add_argument("--iface", default=None,
                        help="force a base Wi-Fi interface to audit (e.g. wlan0)")
    parser.add_argument("--mon-iface", default=None,
                        help="override the generated monitor interface name")
    parser.add_argument("--config-out", default=DEFAULT_CONFIG,
                        help="where to write config.toml (default: %s)" % DEFAULT_CONFIG)
    parser.add_argument("--state-out", default=DEFAULT_STATE,
                        help="where to write doctor.json (default: %s)" % DEFAULT_STATE)
    parser.add_argument("--deep-scan", action="store_true",
                        help="run a live aireplay-ng injection probe (needs root, "
                             "temporarily creates a monitor vif)")
    parser.add_argument("--print-only", action="store_true",
                        help="audit and print, do not write any file")
    parser.add_argument("--json", action="store_true",
                        help="print the raw report as JSON")
    args = parser.parse_args(argv)

    report = audit(forced_iface=args.iface, deep=args.deep_scan)
    if args.mon_iface:
        report["mon_iface"] = args.mon_iface[:MAX_IFACE_LEN]

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_summary(report)

    if not report.get("ok"):
        return 2

    if report["injection"]:
        info("recommendation: FULL active mode (injection available).")
    else:
        info("recommendation: PASSIVE-only mode (no injection available).")

    if args.print_only:
        return 0

    try:
        write_file(args.config_out, render_config(report, args.config_out))
        write_file(args.state_out, json.dumps(report, indent=2) + "\n")
    except OSError as exc:
        err("could not write config/state: %s" % exc)
        return 3

    if not args.json:
        ok("wrote %s" % args.config_out)
        ok("wrote %s" % args.state_out)
    return 0


if __name__ == "__main__":
    sys.exit(main())