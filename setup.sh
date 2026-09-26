#!/usr/bin/env bash
#
# setup.sh -- install jayofelony's Pwnagotchi on PC / Linux (x86_64, Kali)
# without rewriting the upstream codebase.
#
# What it does:
#   1. apt-installs the system packages (bettercap, libpcap-dev, python3-pip,
#      python3-prctl, plus a few supporting tools).
#   2. git clones https://github.com/jayofelony/pwnagotchi (--depth 1).
#   3. installs the off-Pi Python requirements with --break-system-packages and
#      installs the pwnagotchi package itself with --no-deps so pip never tries
#      to pull Pi-only hardware wheels (gpiozero, inky, smbus, spidev, ...).
#   4. applies the 2 known Linux runtime patches (agent.py event loop and
#      __init__.py temperature fallback) -- both idempotent.
#   5. generates the RSA identity in /etc/pwnagotchi/id_rsa with ssh-keygen so
#      the external pwngrid binary is not required.
#
# Safe to re-run.  Override locations with:
#   PWN_HOME=/opt/pwnagotchi-pc PWN_REPO_DIR=... PWN_CONFIG_DIR=/etc/pwnagotchi
set -euo pipefail

PWN_HOME="${PWN_HOME:-/opt/pwnagotchi-pc}"
PWN_REPO_DIR="${PWN_REPO_DIR:-$PWN_HOME/pwnagotchi}"
PWN_CONFIG_DIR="${PWN_CONFIG_DIR:-/etc/pwnagotchi}"
PWN_REPO_URL="https://github.com/jayofelony/pwnagotchi"
PWN_REQ_FILE="$PWN_HOME/requirements-pc.txt"

log()  { printf '\033[1;32m[setup]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[setup]\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m[setup]\033[0m %s\n' "$*" >&2; exit 1; }

require_root() {
    [ "$(id -u)" = "0" ] || die "must be run as root: sudo $0"
}

install_system_packages() {
    log "installing system packages ..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -y
    # Required by the spec:
    #   bettercap libpcap-dev python3-pip python3-prctl
    # Supporting packages needed for a working PC install:
    #   git/iw           -> clone + hardware audit
    #   aircrack-ng      -> optional live injection probe (doctor.py --deep-scan)
    #   python3-dbus     -> dbus-python (bt-tether plugin) without pip building it
    #   python3-pil      -> Pillow, imported unconditionally by pwnagotchi's UI
    #   fonts-dejavu     -> DejaVuSansMono used to render the UI canvas
    #   openssh-client   -> ssh-keygen for the local RSA identity
    #   nmcli via network-manager is expected to already exist on Kali
    apt-get install -y --no-install-recommends \
        bettercap \
        libpcap-dev \
        python3-pip \
        python3-prctl \
        git \
        iw \
        aircrack-ng \
        python3-dbus \
        python3-pil \
        fonts-dejavu \
        openssh-client \
        net-tools
}

clone_repo() {
    mkdir -p "$PWN_HOME"
    if [ -d "$PWN_REPO_DIR/.git" ]; then
        log "repo already present, updating (depth 1, fast-forward only) ..."
        git -C "$PWN_REPO_DIR" pull --ff-only --depth 1 || warn "git pull failed, keeping local tree"
    else
        log "cloning $PWN_REPO_URL (--depth 1) into $PWN_REPO_DIR ..."
        git clone --depth 1 "$PWN_REPO_URL" "$PWN_REPO_DIR"
    fi
    [ -f "$PWN_REPO_DIR/pwnagotchi/agent.py" ] || die "clone looks incomplete ($PWN_REPO_DIR)"
}

install_python_requirements() {
    log "installing off-Pi Python requirements ..."

    # Upstream keeps its dependencies in pyproject.toml.  Everything here is the
    # non-Pi subset of those dependencies; the Pi-only hardware wheels are
    # deliberately excluded because they cannot build/run on x86_64:
    #   gpiozero inky rpi-lgpio rpi_hardware_pwm smbus smbus2 spidev pisugar
    # dbus-python is intentionally absent too -- python3-dbus (apt) covers it.
    cat > "$PWN_REQ_FILE" <<'REQS'
PyYAML
file-read-backwards
flask
flask-cors
flask-wtf
pycryptodome
python-dateutil
requests
scapy
setuptools
tomlkit
toml
tweepy
websockets
Pillow
REQS

    python3 -m pip install --break-system-packages --upgrade -r "$PWN_REQ_FILE"

    # Install pwnagotchi itself with --no-deps so the resolver never drags in
    # gpiozero/inky/smbus/spidev/pisugar (which would abort the whole install).
    # Editable is preferred: the clone is used in place, nothing is rewritten.
    if python3 -m pip install --break-system-packages --no-deps --no-build-isolation -e "$PWN_REPO_DIR"; then
        log "installed pwnagotchi in editable mode (--no-deps)"
    elif python3 -m pip install --break-system-packages --no-deps --no-build-isolation "$PWN_REPO_DIR"; then
        log "installed pwnagotchi (--no-deps)"
    else
        warn "pip install of pwnagotchi failed; start.sh will run it from the clone via PYTHONPATH"
    fi

    # Verify that the pwnagotchi package (and its subpackages) are actually
    # importable.  If not, start.sh transparently falls back to executing the
    # clone via PYTHONPATH, so a packaging surprise can never stop the unit.
    if python3 -c "import pwnagotchi.utils, pwnagotchi.grid, pwnagotchi.bettercap, pwnagotchi.ui.display" >/dev/null 2>&1; then
        log "python import check OK"
    else
        warn "python import check failed; start.sh will use PYTHONPATH module execution"
    fi
}

patch_runtime() {
    log "applying Linux runtime patches ..."
    python3 - "$PWN_REPO_DIR" <<'PYPATCH'
import io
import os
import sys

repo = sys.argv[1]
agent_path = os.path.join(repo, "pwnagotchi", "agent.py")
init_path = os.path.join(repo, "pwnagotchi", "__init__.py")


def read(path):
    with io.open(path, "r", encoding="utf-8") as fp:
        return fp.read()


def write(path, text):
    with io.open(path, "w", encoding="utf-8") as fp:
        fp.write(text)


# --- patch (a): asyncio.get_event_loop() -> asyncio.new_event_loop() ----------
# On Python 3.10+/3.12 `get_event_loop()` raises/gets deprecated when there is
# no running loop in the thread.  The event-poller thread is exactly that case,
# so allocate a brand new loop instead.
text = read(agent_path)
if "asyncio.new_event_loop()" in text:
    print("  [a] agent.py already patched")
else:
    fixed, changed = [], False
    for line in text.splitlines(keepends=True):
        if "Event Polling" in line and "asyncio.get_event_loop()" in line:
            line = line.replace("asyncio.get_event_loop()", "asyncio.new_event_loop()")
            changed = True
        fixed.append(line)
    if not changed:
        sys.exit("  [a] FAILED: could not find the Event Polling line in agent.py")
    write(agent_path, "".join(fixed))
    print("  [a] patched agent.py: asyncio.new_event_loop()")

# --- patch (b): temperature() must not crash without a thermal zone -----------
# Desktops/laptops without /sys/class/thermal/thermal_zone0/temp (or with the
# file present but unreadable) used to raise FileNotFoundError and kill the
# stats thread.  Return a safe 35 C fallback on PC instead.
text = read(init_path)
old_block = (
    "def temperature(celsius=True):\n"
    "    with open('/sys/class/thermal/thermal_zone0/temp', 'rt') as fp:\n"
    "        temp = int(fp.read().strip())\n"
    "    c = int(temp / 1000)\n"
    "    return c if celsius else ((c * (9 / 5)) + 32)\n"
)
new_block = (
    "def temperature(celsius=True):\n"
    "    try:\n"
    "        with open('/sys/class/thermal/thermal_zone0/temp', 'rt') as fp:\n"
    "            temp = int(fp.read().strip())\n"
    "        c = int(temp / 1000)\n"
    "    except Exception:\n"
    "        # PC / VM without a readable thermal zone: report a safe 35 C.\n"
    "        c = 35\n"
    "    return c if celsius else ((c * (9 / 5)) + 32)\n"
)
if "PC / VM without a readable thermal zone" in text:
    print("  [b] __init__.py already patched")
elif old_block in text:
    write(init_path, text.replace(old_block, new_block, 1))
    print("  [b] patched __init__.py: temperature() fallback")
else:
    sys.exit("  [b] FAILED: temperature() block not found (upstream changed?)")
PYPATCH
}

make_dirs() {
    log "creating $PWN_CONFIG_DIR layout ..."
    mkdir -p "$PWN_CONFIG_DIR"/log \
             "$PWN_CONFIG_DIR"/handshakes \
             "$PWN_CONFIG_DIR"/conf.d \
             "$PWN_CONFIG_DIR"/custom-plugins \
             "$PWN_CONFIG_DIR"/backups
    chmod 700 "$PWN_CONFIG_DIR"
}

generate_keys() {
    local key="$PWN_CONFIG_DIR/id_rsa"
    log "ensuring RSA identity in $PWN_CONFIG_DIR ..."
    if [ -s "$key" ] && [ -s "$key.pub" ]; then
        log "identity already present, keeping it"
        return 0
    fi
    rm -f "$key" "$key.pub"
    # `-m PEM` forces a PKCS#1 private key that pycryptodome's RSA.importKey can
    # read; the public key is then re-exported as PKCS#8 PEM for the same
    # reason. This removes the dependency on the external `pwngrid` binary.
    ssh-keygen -t rsa -b 2048 -m PEM -N "" -C "pwnagotchi@$(hostname)" -f "$key" >/dev/null
    if ssh-keygen -e -m PKCS8 -f "$key.pub" > "$key.pub.tmp" 2>/dev/null; then
        mv "$key.pub.tmp" "$key.pub"
    else
        rm -f "$key.pub.tmp"
        warn "could not re-export public key as PKCS#8 PEM, keeping OpenSSH format"
    fi
    chmod 600 "$key"
    chmod 644 "$key.pub"
    log "generated $key and $key.pub"
}

write_env() {
    cat > "$PWN_HOME/env.sh" <<ENVEOF
# Auto-generated by setup.sh -- resolved install locations for start.sh.
: "\${PWN_HOME:=$PWN_HOME}"
: "\${PWN_REPO_DIR:=$PWN_REPO_DIR}"
: "\${PWN_CONFIG_DIR:=$PWN_CONFIG_DIR}"
export PWN_HOME PWN_REPO_DIR PWN_CONFIG_DIR
ENVEOF
    log "wrote $PWN_HOME/env.sh"
}

link_launcher() {
    local script_dir="$1"
    [ -f "$script_dir/start.sh" ] || return 0
    chmod +x "$script_dir/start.sh" "$script_dir/doctor.py" 2>/dev/null || true
    ln -sf "$script_dir/start.sh" /usr/local/bin/pwnagotchi-pc
    log "linked /usr/local/bin/pwnagotchi-pc -> $script_dir/start.sh"
}

generate_config() {
    local script_dir="$1"
    if [ -f "$script_dir/doctor.py" ]; then
        log "auditing Wi-Fi hardware ..."
        python3 "$script_dir/doctor.py" \
            --config-out "$PWN_CONFIG_DIR/config.toml" \
            --state-out "$PWN_CONFIG_DIR/doctor.json" \
            || warn "doctor.py did not complete; start.sh will re-run it"
    fi
}

print_next_steps() {
    cat <<EOF

$(printf '\033[1;32m=== setup complete ===\033[0m')

  pwnagotchi  : $PWN_REPO_DIR (patched in place, editable install)
  config      : $PWN_CONFIG_DIR/config.toml   (regenerated by doctor.py)
  identity    : $PWN_CONFIG_DIR/id_rsa
  logs        : $PWN_CONFIG_DIR/log/
  web ui      : http://<host>:8080 (once running)

  Start the unit:   sudo pwnagotchi-pc
                    (or run the start.sh you extracted next to this script)
EOF
}

main() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    require_root
    install_system_packages
    clone_repo
    install_python_requirements
    patch_runtime
    make_dirs
    generate_keys
    write_env
    link_launcher "$script_dir"
    generate_config "$script_dir"
    print_next_steps
}

main "$@"