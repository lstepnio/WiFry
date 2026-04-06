#!/usr/bin/env bash
#
# WiFry - IP Video Edition
# Custom RPi Image Builder
#
# Builds a flashable .img.xz file with WiFry pre-installed.
# Based on pi-gen (the official Raspberry Pi OS image builder).
#
# Prerequisites (build machine — Linux x86_64 or ARM64):
#   - Docker (recommended) or native build deps
#   - ~10GB free disk space
#   - Internet access
#
# Usage:
#   ./build-image.sh [version]
#
# Output:
#   image-build/output/wifry-<version>-rpi-arm64.img.xz
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="${1:-$(date +%Y%m%d)}"
OUTPUT_DIR="$SCRIPT_DIR/output"
PIGEN_DIR="$SCRIPT_DIR/pi-gen"
# Put WiFry install inside stage2 as extra substages (not a separate stage)
# This avoids rootfs chaining issues with custom stage names
WIFRY_STAGE="$PIGEN_DIR/stage2"

echo "╔══════════════════════════════════════════╗"
echo "║  WiFry Image Builder v${VERSION}             ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ─── Step 1: Clone pi-gen ────────────────────────────────────────────

if [[ ! -d "$PIGEN_DIR" ]]; then
    echo "Cloning pi-gen..."
    git clone --depth 1 --branch arm64 https://github.com/RPi-Distro/pi-gen.git "$PIGEN_DIR"
else
    echo "pi-gen already cloned."
fi

# ─── Step 2: Configure pi-gen ────────────────────────────────────────

echo "Configuring pi-gen..."

cat > "$PIGEN_DIR/config" <<EOF
IMG_NAME=wifry-${VERSION}
RELEASE=bookworm
TARGET_HOSTNAME=wifry
FIRST_USER_NAME=pi
FIRST_USER_PASS=wifry
ENABLE_SSH=1
LOCALE_DEFAULT=en_US.UTF-8
KEYBOARD_KEYMAP=us
KEYBOARD_LAYOUT="English (US)"
TIMEZONE_DEFAULT=America/Denver
STAGE_LIST="stage0 stage1 stage2"
EOF

# Skip stages 3-5 (desktop, full desktop, etc.) — we want Lite + WiFry
touch "$PIGEN_DIR/stage3/SKIP" "$PIGEN_DIR/stage4/SKIP" "$PIGEN_DIR/stage5/SKIP"
touch "$PIGEN_DIR/stage4/SKIP_IMAGES" "$PIGEN_DIR/stage5/SKIP_IMAGES"

# Comprehensive pi-gen stage2 patches for arm64 bookworm compatibility.
# Many rpi-* packages don't exist in the standard repos for arm64.
echo "Applying stage2 compatibility patches..."

# Remove all unavailable rpi-* packages from every package file in stage2
find "$PIGEN_DIR/stage2" -name "00-packages*" -type f | while read pkgfile; do
    sed -i 's/rpi-swap//g; s/rpi-loop-utils//g; s/rpi-usb-gadget//g; s/rpi-cloud-init-mods//g' "$pkgfile"
    echo "  Patched: $pkgfile"
done

# Make all systemctl enable calls non-fatal (missing services)
find "$PIGEN_DIR/stage2" -name "*.sh" -type f | while read script; do
    if grep -q "systemctl enable" "$script"; then
        sed -i 's/systemctl enable \(.*\)/systemctl enable \1 || true/g' "$script"
        echo "  Patched systemctl: $script"
    fi
done

# Skip cloud-init substage entirely (rpi-cloud-init-mods unavailable)
if [[ -d "$PIGEN_DIR/stage2/04-cloud-init" ]]; then
    touch "$PIGEN_DIR/stage2/04-cloud-init/SKIP"
    echo "  Skipped: stage2/04-cloud-init"
fi

# Skip mathematica EULA (not needed)
if [[ -d "$PIGEN_DIR/stage2/03-accept-mathematica-eula" ]]; then
    touch "$PIGEN_DIR/stage2/03-accept-mathematica-eula/SKIP"
    echo "  Skipped: stage2/03-accept-mathematica-eula"
fi

echo "Stage2 patches complete."

# Fix Debian GPG key issue: download fresh debian-archive-keyring and
# install it into the rootfs before pi-gen runs apt-get update.
# We do this by patching stage0's prerun.sh to fetch and install the keyring.
PRERUN="$PIGEN_DIR/stage0/prerun.sh"
if [[ -f "$PRERUN" ]]; then
    cat >> "$PRERUN" <<'KEYFIX'

# WiFry patch: install fresh Debian archive keyring into rootfs
echo "WiFry: Fetching fresh debian-archive-keyring..."
KEYRING_URL="http://ftp.debian.org/debian/pool/main/d/debian-archive-keyring/debian-archive-keyring_2025.1_all.deb"
curl -sL -o /tmp/debian-archive-keyring.deb "$KEYRING_URL" || \
    wget -q -O /tmp/debian-archive-keyring.deb "$KEYRING_URL" 2>/dev/null
if [ -f /tmp/debian-archive-keyring.deb ]; then
    dpkg-deb -x /tmp/debian-archive-keyring.deb "${ROOTFS_DIR}/"
    echo "WiFry: Fresh keyring installed into rootfs"
    rm -f /tmp/debian-archive-keyring.deb
fi
KEYFIX
    echo "Patched $PRERUN with keyring install"
fi

# ─── Step 3: Create WiFry custom stage ───────────────────────────────

echo "Creating WiFry stage..."

# Add WiFry substages to stage2 (numbered high so they run last)
mkdir -p "$WIFRY_STAGE/10-wifry-deps/files"
mkdir -p "$WIFRY_STAGE/11-wifry-install/files"

# ── Substage 00: Install system dependencies ──

cat > "$WIFRY_STAGE/10-wifry-deps/00-packages" <<'PACKAGES'
python3
python3-venv
python3-pip
hostapd
dnsmasq
bridge-utils
iproute2
iptables
iptables-persistent
tshark
wireless-tools
iw
nodejs
npm
git
ffmpeg
v4l-utils
hping3
iperf3
wireguard-tools
openvpn
strongswan
strongswan-swanctl
curl
jq
rsync
PACKAGES

cat > "$WIFRY_STAGE/10-wifry-deps/01-run.sh" <<'DEPS_SCRIPT'
#!/bin/bash -e

# Install binary dependencies
ARCH=$(dpkg --print-architecture)

# Cloudflare Tunnel
if ! command -v cloudflared &>/dev/null; then
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}" -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
fi

# CoreDNS
if ! command -v coredns &>/dev/null; then
    COREDNS_VER="1.11.3"
    curl -sL "https://github.com/coredns/coredns/releases/download/v${COREDNS_VER}/coredns_${COREDNS_VER}_linux_${ARCH}.tgz" | tar xz -C /usr/local/bin/
    chmod +x /usr/local/bin/coredns
fi

# Ookla Speedtest CLI
if ! command -v speedtest &>/dev/null; then
    curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash
    apt-get install -y speedtest || true
fi
DEPS_SCRIPT
chmod +x "$WIFRY_STAGE/10-wifry-deps/01-run.sh"

# ── Substage 01: Install WiFry application ──

# Build frontend on the build machine first
echo "Building frontend for image..."
cd "$PROJECT_DIR/frontend"
if command -v npm &>/dev/null; then
    npm run build 2>/dev/null || echo "Frontend build skipped (run npm install first)"
fi
cd "$SCRIPT_DIR"

# Copy WiFry source into the stage
rsync -a --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
    --exclude '.git' --exclude '.pytest_cache' --exclude 'image-build' \
    "$PROJECT_DIR/" "$WIFRY_STAGE/11-wifry-install/files/wifry/"

# Host-side script: copy files into rootfs before chroot runs
cat > "$WIFRY_STAGE/11-wifry-install/00-run.sh" <<'COPY_SCRIPT'
#!/bin/bash -e
# Runs on HOST — copy WiFry files into the rootfs
INSTALL_DIR="${ROOTFS_DIR}/opt/wifry"
mkdir -p "$INSTALL_DIR"
if [[ -d "${STAGE_WORK_DIR}/11-wifry-install/files/wifry" ]]; then
    cp -r "${STAGE_WORK_DIR}/11-wifry-install/files/wifry/"* "$INSTALL_DIR/" || true
fi
# Fallback: check pi-gen's files directory
if [[ ! -f "$INSTALL_DIR/VERSION" ]] && [[ -d "files/wifry" ]]; then
    cp -r files/wifry/* "$INSTALL_DIR/" || true
fi
echo "WiFry files copied to $INSTALL_DIR"
ls "$INSTALL_DIR/" || echo "WARNING: install dir empty"
COPY_SCRIPT
chmod +x "$WIFRY_STAGE/11-wifry-install/00-run.sh"

cat > "$WIFRY_STAGE/11-wifry-install/01-run-chroot.sh" <<'INSTALL_SCRIPT'
#!/bin/bash -e

INSTALL_DIR="/opt/wifry"
DATA_DIR="/var/lib/wifry"
WIFRY_USER="wifry"

# Create user
useradd --system --create-home --shell /usr/sbin/nologin "$WIFRY_USER" || true
usermod -aG netdev "$WIFRY_USER" || true

# Code already copied by host-side 00-run.sh
chown -R "$WIFRY_USER:$WIFRY_USER" "$INSTALL_DIR" || true

# Create data directories
for dir in captures reports sessions segments bundles annotations \
           adb-files hdmi-captures coredns teleport network-profiles; do
    mkdir -p "$DATA_DIR/$dir"
done
mkdir -p /var/log/wifry
chown -R "$WIFRY_USER:$WIFRY_USER" "$DATA_DIR" /var/log/wifry

# Python venv
sudo -u "$WIFRY_USER" python3 -m venv "$INSTALL_DIR/backend/.venv"
sudo -u "$WIFRY_USER" "$INSTALL_DIR/backend/.venv/bin/pip" install --upgrade pip -q
sudo -u "$WIFRY_USER" "$INSTALL_DIR/backend/.venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" -q

# Sudoers
install -m 0440 "$INSTALL_DIR/setup/wifry-sudoers" /etc/sudoers.d/wifry

# Login banner
install -m 0644 "$INSTALL_DIR/setup/wifry-motd.sh" /etc/profile.d/wifry-motd.sh

# Systemd services
cp "$INSTALL_DIR/setup/wifry-backend.service" /etc/systemd/system/
cp "$INSTALL_DIR/setup/wifry-frontend.service" /etc/systemd/system/
cp "$INSTALL_DIR/setup/wifry-recovery.service" /etc/systemd/system/

systemctl enable wifry-backend.service
systemctl enable wifry-frontend.service
systemctl enable wifry-recovery.service
systemctl enable hostapd.service
systemctl enable dnsmasq.service

# Unmask hostapd (masked by default in RPi OS)
systemctl unmask hostapd

# hostapd config
WLAN_IFACE="wlan0"
cat > /etc/hostapd/hostapd.conf <<HOSTAPD
interface=${WLAN_IFACE}
driver=nl80211
ssid=WiFry
utf8_ssid=1
hw_mode=g
channel=6
ieee80211n=1
ieee80211ax=1
wpa=2
wpa_passphrase=wifry1234
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
country_code=US
ieee80211d=1
wmm_enabled=1
macaddr_acl=0
auth_algs=1
ignore_broadcast_ssid=0
HOSTAPD

echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > /etc/default/hostapd

# dnsmasq config
cat > /etc/dnsmasq.d/wifry.conf <<DNSMASQ
interface=${WLAN_IFACE}
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.200,255.255.255.0,24h
dhcp-option=6,192.168.4.1
server=8.8.8.8
no-resolv
log-queries
log-dhcp
log-facility=/var/log/wifry-dnsmasq.log
DNSMASQ

# Static IP + fallback
cat >> /etc/dhcpcd.conf <<DHCPCD

# WiFry AP config
interface ${WLAN_IFACE}
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant

# WiFry fallback — always reachable for recovery
interface eth0
    static ip_address=169.254.42.1/16
    nolink
DHCPCD

# IP forwarding
echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf

# NAT rules (applied on boot via iptables-persistent)
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
netfilter-persistent save

# Write version file
echo "wifry-$(date +%Y%m%d)" > /opt/wifry/VERSION

INSTALL_SCRIPT
chmod +x "$WIFRY_STAGE/11-wifry-install/01-run-chroot.sh"

# stage2 already has EXPORT_IMAGE — no need to add it

# ─── Step 4: Build the image ─────────────────────────────────────────

echo ""
echo "Building RPi image (this takes 20-40 minutes)..."
echo ""

cd "$PIGEN_DIR"

if command -v docker &>/dev/null; then
    echo "Using Docker build method..."
    ./build-docker.sh
else
    echo "Using native build method..."
    echo "Note: Requires quemu-user-static and other deps. See pi-gen README."
    ./build.sh
fi

# ─── Step 5: Collect output ──────────────────────────────────────────

mkdir -p "$OUTPUT_DIR"

# Find the built image
IMAGE=$(find "$PIGEN_DIR/deploy" -name "*.img.xz" -type f | head -1)
if [[ -n "$IMAGE" ]]; then
    FINAL_NAME="wifry-${VERSION}-rpi-arm64.img.xz"
    cp "$IMAGE" "$OUTPUT_DIR/$FINAL_NAME"

    # Generate checksum
    sha256sum "$OUTPUT_DIR/$FINAL_NAME" > "$OUTPUT_DIR/$FINAL_NAME.sha256"

    SIZE=$(du -sh "$OUTPUT_DIR/$FINAL_NAME" | awk '{print $1}')

    echo ""
    echo "╔══════════════════════════════════════════╗"
    echo "║  Image Build Complete!                   ║"
    echo "╚══════════════════════════════════════════╝"
    echo ""
    echo "  Image: $OUTPUT_DIR/$FINAL_NAME"
    echo "  Size:  $SIZE"
    echo "  SHA256: $(cat "$OUTPUT_DIR/$FINAL_NAME.sha256" | awk '{print $1}')"
    echo ""
    echo "  Flash to SD card:"
    echo "    xz -d $FINAL_NAME"
    echo "    sudo dd if=wifry-${VERSION}-rpi-arm64.img of=/dev/sdX bs=4M status=progress"
    echo ""
    echo "  Or use Raspberry Pi Imager:"
    echo "    Choose 'Use custom' and select $FINAL_NAME"
    echo ""
else
    echo "ERROR: No image found in pi-gen/deploy/"
    echo "Check pi-gen build logs for errors."
    exit 1
fi
