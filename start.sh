#!/usr/bin/env bash
#
# start.sh -- one-shot runner for jayofelony's Pwnagotchi on PC / Linux (x86_64).
#
#   1. runs doctor.py       -> audits Wi-Fi hardware & writes config.toml
#                              (active mode if injection works, else passive)
#   2. starts grid_mock     -> minimal local pwngrid-peer on 127.0.0.1:8666
#   3. unmanages the Wi-Fi card from NetworkManager and enables monitor mode
#   4. starts Bettercap     -> REST API on 127.0.0.1:8081
#   5. starts Pwnagotchi
#   6. restores the network / kills the helpers on Ctrl+C (or any exit)
#
# Usage:
#   sudo ./start.sh
#   sudo PWN_IFACE=wlan1 ./start.sh        # force a specific radio
#   sudo PWN_DEEP_SCAN=1 ./start.sh        # live aireplay injection probe
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PWN_HOME="${PWN_HOME:-/opt/pwnagotchi-pc}"
# shellcheck source=/dev/null
[ -f "$PWN_HOME/env.sh" ] && . "$PWN_HOME/env.sh"
PWN_REPO_DIR="${PWN_REPO_DIR:-$PWN_HOME/pwnagotchi}"
PWN_CONFIG_DIR="${PWN_CONFIG_DIR:-/etc/pwnagotchi}"
CONFIG="$PWN_CONFIG_DIR/config.toml"
STATE="$PWN_CONFIG_DIR/doctor.json"
LOG_DIR="$PWN_CONFIG_DIR/log"
GRID_MOCK="$PWN_HOME/grid_mock.py"

GRID_PORT="${PWN_GRID_PORT:-8666}"
BETTERCAP_PORT="${PWN_BETTERCAP_PORT:-8081}"
BETTERCAP_USER="pwnagotchi"
BETTERCAP_PASS="pwnagotchi"

BASE_IFACE=""
MON_IFACE=""
MODE=""
CREATED_VIF=0
GRID_PID=""
BETTERCAP_PID=""
CLEANUP_DONE=0

log()  { printf '\033[1;32m[start]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[start]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[start]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

require_root() {
    [ "$(id -u)" = "0" ] || die "must be run as root: sudo $0"
}

run_doctor() {
    local -a cmd=(python3 "$SCRIPT_DIR/doctor.py" --config-out "$CONFIG" --state-out "$STATE")
    [ -n "${PWN_IFACE:-}" ] && cmd+=(--iface "$PWN_IFACE")
    [ "${PWN_DEEP_SCAN:-0}" = "1" ] && cmd+=(--deep-scan)
    "${cmd[@]}" || die "hardware audit failed (no usable Wi-Fi interface?)"
}

_state_get() {
    python3 -c 'import json, sys
try:
    print(json.load(open(sys.argv[1])).get(sys.argv[2], ""))
except Exception:
    print("")' "$STATE" "$1"
}

read_state() {
    BASE_IFACE="$(_state_get base_iface)"
    MON_IFACE="$(_state_get mon_iface)"
    MODE="$(_state_get mode)"
    [ -n "$BASE_IFACE" ] && [ -n "$MON_IFACE" ] || die "could not read $STATE"
}

# ---------------------------------------------------------------------------
# grid_mock: a tiny stand-in for the pwngrid-peer service on 127.0.0.1:8666.
# Pwnagotchi's mesh advertiser hard-codes http://127.0.0.1:8666/api/v1 and will
# crash on startup if nothing answers, so we implement just the endpoints the
# core calls (mesh data/advertise/peers) plus harmless empty replies for the
# grid plugin's inbox/report calls.
# ---------------------------------------------------------------------------
port_in_use() {
    python3 -c 'import socket, sys
s = socket.socket()
try:
    s.bind(("127.0.0.1", int(sys.argv[1])))
except OSError:
    sys.exit(0)
else:
    sys.exit(1)
finally:
    s.close()' "$GRID_PORT"
}

write_grid_mock() {
    cat > "$GRID_MOCK" <<'PYMOCK'
#!/usr/bin/env python3
"""Minimal pwngrid-peer replacement for a PC pwnagotchi (port 8666)."""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

API = "/api/v1"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    advertisement = {}

    def log_message(self, *args):  # keep the console quiet
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b""
            return json.loads(raw.decode("utf-8")) if raw else {}
        except Exception:
            return {}

    def do_POST(self):
        path = urlparse(self.path).path
        obj = self._read_json()
        if path == API + "/mesh/data":
            Handler.advertisement = obj
        # every POST the core makes (/mesh/true, /mesh/data, /data,
        # /report/ap, /unit/<to>/inbox, ...) is happy with an empty JSON object
        self._send({})

    def do_GET(self):
        path = urlparse(self.path).path
        if path == API + "/mesh/peers":
            return self._send([])
        if path == API + "/mesh/data":
            return self._send(Handler.advertisement)
        if path == API + "/mesh/memory":
            return self._send({"total": 0, "free": 0, "used": 0})
        if path == API + "/inbox":
            return self._send({"messages": [], "total": 0, "page": 1, "pages": 1})
        if path == API + "/uptime":
            return self._send({"isUp": True})
        return self._send({})


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8666
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    server.serve_forever()


if __name__ == "__main__":
    main()
PYMOCK
}

start_grid_mock() {
    if port_in_use; then
        log "port $GRID_PORT is already in use (real pwngrid-peer?), skipping mock"
        return 0
    fi
    write_grid_mock
    python3 "$GRID_MOCK" "$GRID_PORT" >>"$LOG_DIR/grid_mock.log" 2>&1 &
    GRID_PID=$!
    sleep 0.5
    if kill -0 "$GRID_PID" 2>/dev/null; then
        log "grid_mock listening on 127.0.0.1:$GRID_PORT (pid $GRID_PID)"
    else
        warn "grid_mock exited immediately, see $LOG_DIR/grid_mock.log"
        GRID_PID=""
    fi
}

prepare_wifi() {
    log "unmanaging $BASE_IFACE from NetworkManager and enabling monitor mode ..."

    command -v rfkill >/dev/null 2>&1 && { rfkill unblock wifi || true; }

    if command -v nmcli >/dev/null 2>&1; then
        nmcli device set "$BASE_IFACE" managed no >/dev/null 2>&1 \
            || warn "nmcli could not unmanage $BASE_IFACE (continuing anyway)"
        sleep 1
    else
        warn "nmcli not found; assuming $BASE_IFACE is not managed"
    fi

    ip link set "$BASE_IFACE" down >/dev/null 2>&1 || true

    if iw dev "$BASE_IFACE" interface add "$MON_IFACE" type monitor 2>/dev/null; then
        CREATED_VIF=1
        log "created dedicated monitor interface $MON_IFACE"
    else
        warn "driver refused a monitor vif; converting $BASE_IFACE in place"
        if iw dev "$BASE_IFACE" set type monitor 2>/dev/null; then
            MON_IFACE="$BASE_IFACE"
            CREATED_VIF=0
            # keep config.toml + doctor.json pointing at the effective iface
            python3 "$SCRIPT_DIR/doctor.py" --iface "$BASE_IFACE" --mon-iface "$BASE_IFACE" \
                --config-out "$CONFIG" --state-out "$STATE" >/dev/null 2>&1 \
                || warn "could not refresh $CONFIG for in-place monitor mode"
        else
            die "could not put $BASE_IFACE into monitor mode (driver lacks support)"
        fi
    fi

    ip link set "$MON_IFACE" up >/dev/null 2>&1 || warn "could not bring $MON_IFACE up"
    iw dev "$MON_IFACE" set power_save off >/dev/null 2>&1 || true
    log "monitor interface ready: $MON_IFACE (mode: ${MODE:-unknown})"
}

bettercap_api_ready() {
    python3 -c 'import base64, sys, urllib.request
port, user, pw = sys.argv[1], sys.argv[2], sys.argv[3]
req = urllib.request.Request("http://127.0.0.1:%s/api/session" % port)
req.add_header("Authorization", "Basic " + base64.b64encode(("%s:%s" % (user, pw)).encode()).decode())
try:
    urllib.request.urlopen(req, timeout=3).read()
    sys.exit(0)
except Exception:
    sys.exit(1)' "$BETTERCAP_PORT" "$BETTERCAP_USER" "$BETTERCAP_PASS"
}

start_bettercap() {
    command -v bettercap >/dev/null 2>&1 || die "bettercap not found on PATH"
    log "starting bettercap (REST API on 127.0.0.1:$BETTERCAP_PORT) ..."
    : >"$LOG_DIR/bettercap.log"

    bettercap -no-colors -no-history -iface "$MON_IFACE" \
        -eval "set api.rest.username $BETTERCAP_USER; set api.rest.password $BETTERCAP_PASS; set api.rest.address 127.0.0.1; set api.rest.port $BETTERCAP_PORT; api.rest on" \
        </dev/null >>"$LOG_DIR/bettercap.log" 2>&1 &
    BETTERCAP_PID=$!

    local i
    for i in $(seq 1 30); do
        if bettercap_api_ready; then
            log "bettercap REST API is up (pid $BETTERCAP_PID)"
            return 0
        fi
        if ! kill -0 "$BETTERCAP_PID" 2>/dev/null; then
            err "bettercap exited during startup, last log lines:"
            tail -n 20 "$LOG_DIR/bettercap.log" >&2 || true
            BETTERCAP_PID=""
            return 1
        fi
        sleep 1
    done
    warn "timed out waiting for the bettercap REST API (see $LOG_DIR/bettercap.log)"
    return 1
}

run_pwnagotchi() {
    export PYTHONPATH="$PWN_REPO_DIR${PYTHONPATH:+:$PYTHONPATH}"

    # Debian python3-pycryptodome installs as 'Cryptodome'. Auto-bridge to 'Crypto' if needed.
    python3 -c "
try:
    import Crypto
except ImportError:
    try:
        import Cryptodome, os
        src = os.path.dirname(Cryptodome.__file__)
        dst = os.path.join(os.path.dirname(src), 'Crypto')
        if not os.path.exists(dst):
            os.symlink(src, dst)
    except Exception:
        pass
" 2>/dev/null || true

    # Pillow 10+ removed FreeTypeFont.getsize(). Auto-patch __init__.py if missing.
    python3 -c "
import os
init_p = os.path.join('$PWN_REPO_DIR', 'pwnagotchi', '__init__.py')
if os.path.isfile(init_p):
    with open(init_p, 'r', encoding='utf-8') as f:
        src = f.read()
    if '_pwn_getsize' not in src:
        patch = '''try:
    import PIL.ImageFont
    def _pwn_getsize(self, text, *args, **kwargs):
        bbox = self.getbbox(text, *args, **kwargs)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])
    if not hasattr(PIL.ImageFont.FreeTypeFont, 'getsize'):
        PIL.ImageFont.FreeTypeFont.getsize = _pwn_getsize
    if not hasattr(PIL.ImageFont.ImageFont, 'getsize'):
        PIL.ImageFont.ImageFont.getsize = _pwn_getsize
except Exception:
    pass
'''
        with open(init_p, 'w', encoding='utf-8') as f:
            f.write(patch + '\n' + src)
" 2>/dev/null || true

    # Provide a dummy pwngrid stub so upstream subprocess calls never fail with FileNotFoundError
    if ! command -v pwngrid >/dev/null 2>&1; then
        printf '#!/bin/sh\nexit 0\n' > /usr/local/bin/pwngrid 2>/dev/null && chmod +x /usr/local/bin/pwngrid 2>/dev/null || true
    fi

    # Ensure RSA identity keypair exists so pwnagotchi doesn't try calling pwngrid
    python3 -c "
import os, hashlib
try:
    from Crypto.PublicKey import RSA
    d = '$PWN_CONFIG_DIR'
    os.makedirs(d, exist_ok=True)
    priv_p = os.path.join(d, 'id_rsa')
    pub_p = os.path.join(d, 'id_rsa.pub')
    fp_p = os.path.join(d, 'fingerprint')
    if not (os.path.isfile(priv_p) and os.path.isfile(pub_p)):
        k = RSA.generate(2048)
        with open(priv_p, 'wb') as f:
            f.write(k.export_key('PEM'))
        pub_pem = k.publickey().export_key('PEM')
        with open(pub_p, 'wb') as f:
            f.write(pub_pem)
        pem_ascii = pub_pem.decode('ascii')
        if 'RSA PUBLIC KEY' not in pem_ascii:
            pem_ascii = pem_ascii.replace('PUBLIC KEY', 'RSA PUBLIC KEY')
        with open(fp_p, 'w') as f:
            f.write(hashlib.sha256(pem_ascii.encode('ascii')).hexdigest())
        os.chmod(priv_p, 0o600)
        os.chmod(pub_p, 0o644)
except Exception:
    pass
" 2>/dev/null || true

    local -a cmd
    if command -v pwnagotchi >/dev/null 2>&1 \
       && python3 -c "import pwnagotchi.ui.display" >/dev/null 2>&1; then
        cmd=(pwnagotchi)
    else
        warn "pwnagotchi entry point unusable, running the clone via 'python3 -m pwnagotchi.cli'"
        cmd=(python3 -m pwnagotchi.cli)
    fi
    log "launching pwnagotchi (Ctrl+C to stop) ..."
    # -C = upstream defaults.toml (auto-provisioned), -U = our generated config
    "${cmd[@]}" -C "$PWN_CONFIG_DIR/default.toml" -U "$CONFIG" &
    PWN_PID=$!
    wait "$PWN_PID"
    local rc=$?
    PWN_PID=""
    return $rc
}

cleanup() {
    [ "$CLEANUP_DONE" = "1" ] && return 0
    CLEANUP_DONE=1
    trap - EXIT INT TERM
    printf '\n'
    log "shutting down ..."

    local pid alive
    for pid in "$PWN_PID" "$BETTERCAP_PID" "$GRID_PID"; do
        [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
    done

    # give the helpers a moment to exit gracefully, then force-kill leftovers
    local _i
    for _i in 1 2 3 4 5 6 7 8 9 10; do
        alive=0
        for pid in "$PWN_PID" "$BETTERCAP_PID" "$GRID_PID"; do
            [ -n "$pid" ] || continue
            kill -0 "$pid" 2>/dev/null && alive=1
        done
        [ "$alive" = "0" ] && break
        sleep 0.3
    done
    for pid in "$PWN_PID" "$BETTERCAP_PID" "$GRID_PID"; do
        [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null || true
    done

    # put the radio back the way we found it
    if [ -n "$MON_IFACE" ]; then
        if [ "$CREATED_VIF" = "1" ]; then
            iw dev "$MON_IFACE" del >/dev/null 2>&1 && log "removed monitor interface $MON_IFACE"
        elif [ "$MON_IFACE" = "$BASE_IFACE" ]; then
            ip link set "$BASE_IFACE" down >/dev/null 2>&1 || true
            iw dev "$BASE_IFACE" set type managed >/dev/null 2>&1 \
                && log "restored $BASE_IFACE to managed mode"
        fi
    fi
    if [ -n "$BASE_IFACE" ] && command -v nmcli >/dev/null 2>&1; then
        nmcli device set "$BASE_IFACE" managed yes >/dev/null 2>&1 || true
    fi
    [ -n "$BASE_IFACE" ] && ip link set "$BASE_IFACE" up >/dev/null 2>&1 || true

    log "cleanup complete; NetworkManager regained control of ${BASE_IFACE:-the wi-fi card}"
    return 0
}

main() {
    require_root
    [ -f "$SCRIPT_DIR/doctor.py" ] || die "doctor.py not found next to start.sh"
    [ -d "$PWN_REPO_DIR" ] || die "pwnagotchi clone not found at $PWN_REPO_DIR (run setup.sh first)"
    command -v iw >/dev/null 2>&1 || die "'iw' not found on PATH (run setup.sh)"
    mkdir -p "$LOG_DIR" "$PWN_CONFIG_DIR/handshakes"

    log "step 1/5: auditing hardware (doctor.py)"
    run_doctor

    log "step 2/5: reading the auditor report"
    read_state
    log "base iface '$BASE_IFACE' -> monitor iface '$MON_IFACE' (mode: $MODE)"
    if [ "$MODE" = "passive" ]; then
        warn "PASSIVE mode: no injection, deauth/associate are disabled"
    fi

    log "step 3/5: starting grid_mock on port $GRID_PORT"
    start_grid_mock

    log "step 4/5: preparing Wi-Fi and bettercap"
    prepare_wifi
    start_bettercap || die "bettercap did not start (see $LOG_DIR/bettercap.log)"

    log "step 5/5: starting pwnagotchi"
    run_pwnagotchi
}

trap cleanup EXIT
trap 'exit 130' INT TERM
main "$@"