#!/usr/bin/env bash
#
# WiFry - IP Video Edition
# Custom RPi Image Builder (mount-and-inject approach)
#
# Downloads the official Raspberry Pi OS Lite arm64 image, mounts it,
# and injects WiFry code + configuration directly. No QEMU emulation needed.
#
# Prerequisites (build machine — Linux with root/sudo):
#   - losetup, mount, parted, rsync, xz
#   - ~5GB free disk space
#   - Internet access (to download base image)
#
# Usage:
#   sudo ./build-image.sh [version]
#
# Output:
#   image-build/output/wifry-<version>-rpi-arm64.img.xz
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VERSION="${1:-$(date +%Y%m%d)}"
OUTPUT_DIR="$SCRIPT_DIR/output"
WORK_DIR="$SCRIPT_DIR/work"
MOUNT_DIR="$WORK_DIR/mnt"

# RPi OS Lite arm64 base image
RPI_IMAGE_URL="https://downloads.raspberrypi.com/raspios_lite_arm64/images/raspios_lite_arm64-2024-11-19/2024-11-19-raspios-bookworm-arm64-lite.img.xz"
RPI_IMAGE_FILE="$WORK_DIR/raspios-base.img.xz"
WORK_IMAGE="$WORK_DIR/wifry.img"

echo "╔══════════════════════════════════════════════╗"
echo "║  WiFry Image Builder v${VERSION}                  ║"
echo "║  (mount-and-inject method)                   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (sudo)"
    exit 1
fi

mkdir -p "$WORK_DIR" "$OUTPUT_DIR" "$MOUNT_DIR"

# ─── Step 1: Download base RPi OS image ──────────────────────────────

if [[ ! -f "$RPI_IMAGE_FILE" ]]; then
    echo "Downloading Raspberry Pi OS Lite arm64..."
    curl -L -o "$RPI_IMAGE_FILE" "$RPI_IMAGE_URL"
else
    echo "Using cached base image."
fi

# ─── Step 2: Decompress and create working copy ─────────────────────

echo "Decompressing base image..."
xz -dk "$RPI_IMAGE_FILE" 2>/dev/null || true
cp "${RPI_IMAGE_FILE%.xz}" "$WORK_IMAGE"

# Expand image by 2GB to fit WiFry + dependencies list
echo "Expanding image by 2GB..."
truncate -s +2G "$WORK_IMAGE"

# Fix partition table to use the extra space
LOOP_DEV=$(losetup --find --show --partscan "$WORK_IMAGE")
echo "Loop device: $LOOP_DEV"

# Grow the second partition (rootfs) to fill available space
parted -s "$LOOP_DEV" resizepart 2 100%
partprobe "$LOOP_DEV"

# Resize the filesystem
e2fsck -f "${LOOP_DEV}p2" || true
resize2fs "${LOOP_DEV}p2"

# Mount rootfs and boot
mount "${LOOP_DEV}p2" "$MOUNT_DIR"
mount "${LOOP_DEV}p1" "$MOUNT_DIR/boot/firmware"

echo "Image mounted at $MOUNT_DIR"

# ─── Step 3: Pre-configure user (skip first-boot wizard) ────────────

echo "Configuring default user..."

# Create pi user with password 'wifry' (skip the first-boot wizard)
# Password hash for 'wifry': generate with openssl
PASS_HASH=$(openssl passwd -6 "wifry")

# Write userconf file to boot partition (RPi OS reads this on first boot)
echo "pi:${PASS_HASH}" > "$MOUNT_DIR/boot/firmware/userconf.txt"

# Enable SSH
touch "$MOUNT_DIR/boot/firmware/ssh"

# Set hostname
echo "wifry" > "$MOUNT_DIR/etc/hostname"
sed -i 's/raspberrypi/wifry/g' "$MOUNT_DIR/etc/hosts"

# Set timezone
ln -sf /usr/share/zoneinfo/America/Denver "$MOUNT_DIR/etc/localtime"

# Set locale
sed -i 's/# en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' "$MOUNT_DIR/etc/locale.gen"

echo "User 'pi' configured with password 'wifry', SSH enabled."

# ─── Step 4: Copy WiFry application ─────────────────────────────────

echo "Copying WiFry application..."

INSTALL_DIR="$MOUNT_DIR/opt/wifry"
DATA_DIR="$MOUNT_DIR/var/lib/wifry"

mkdir -p "$INSTALL_DIR"
rsync -a --exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' \
    --exclude '.git' --exclude '.pytest_cache' --exclude 'image-build' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

# Copy pre-built frontend if available
if [[ -d "$PROJECT_DIR/frontend/dist" ]]; then
    cp -r "$PROJECT_DIR/frontend/dist" "$INSTALL_DIR/frontend/dist"
fi

# Create data directories
for dir in captures reports sessions segments bundles annotations \
           adb-files hdmi-captures coredns teleport network-profiles; do
    mkdir -p "$DATA_DIR/$dir"
done
# tshark/dumpcap drops privileges and needs world-writable captures dir
chmod 1777 "$DATA_DIR/captures"
mkdir -p "$MOUNT_DIR/var/log/wifry"

# Write version
echo "$VERSION" > "$INSTALL_DIR/VERSION"

echo "WiFry code deployed to /opt/wifry"

# ─── Step 5: Write configuration files ───────────────────────────────

echo "Writing configuration files..."

# hostapd
mkdir -p "$MOUNT_DIR/etc/hostapd"
cat > "$MOUNT_DIR/etc/hostapd/hostapd.conf" <<'HOSTAPD'
interface=wlan0
driver=nl80211
ctrl_interface=/var/run/hostapd
ctrl_interface_group=0
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

echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' > "$MOUNT_DIR/etc/default/hostapd"

# dnsmasq — enable conf-dir so /etc/dnsmasq.d/*.conf files are loaded
# (dnsmasq.conf may not exist in base image — created by first-boot apt install)
if [ -f "$MOUNT_DIR/etc/dnsmasq.conf" ]; then
    sed -i 's/^#conf-dir=\/etc\/dnsmasq.d$/conf-dir=\/etc\/dnsmasq.d/' "$MOUNT_DIR/etc/dnsmasq.conf"
fi
mkdir -p "$MOUNT_DIR/etc/dnsmasq.d"
cat > "$MOUNT_DIR/etc/dnsmasq.d/wifry.conf" <<'DNSMASQ'
interface=wlan0
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.200,255.255.255.0,24h
dhcp-option=6,192.168.4.1
server=8.8.8.8
no-resolv
log-queries
log-dhcp
log-facility=/var/log/wifry-dnsmasq.log
DNSMASQ

# dhcpcd — static IP for AP + fallback
cat >> "$MOUNT_DIR/etc/dhcpcd.conf" <<'DHCPCD'

# WiFry AP config
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant

# WiFry fallback — always reachable for recovery
interface eth0
    static ip_address=169.254.42.1/16
    nolink
DHCPCD

# IP forwarding
echo "net.ipv4.ip_forward=1" >> "$MOUNT_DIR/etc/sysctl.d/99-wifry.conf"

# Sudoers
install -m 0440 "$INSTALL_DIR/setup/wifry-sudoers" "$MOUNT_DIR/etc/sudoers.d/wifry"

# Login banner
install -m 0644 "$INSTALL_DIR/setup/wifry-motd.sh" "$MOUNT_DIR/etc/profile.d/wifry-motd.sh"

echo "Configuration files written."

# ─── Step 6: Install systemd services ────────────────────────────────

echo "Installing systemd services..."

cp "$INSTALL_DIR/setup/wifry-backend.service" "$MOUNT_DIR/etc/systemd/system/"
cp "$INSTALL_DIR/setup/wifry-frontend.service" "$MOUNT_DIR/etc/systemd/system/"
cp "$INSTALL_DIR/setup/wifry-recovery.service" "$MOUNT_DIR/etc/systemd/system/"

# Enable services (create symlinks manually since systemctl won't work outside chroot)
WANTS="$MOUNT_DIR/etc/systemd/system/multi-user.target.wants"
mkdir -p "$WANTS"
ln -sf /etc/systemd/system/wifry-backend.service "$WANTS/wifry-backend.service"
# wifry-frontend (port 3000) is no longer used — FastAPI serves frontend on 8080
ln -sf /etc/systemd/system/wifry-recovery.service "$WANTS/wifry-recovery.service"

# Unmask and enable hostapd
rm -f "$MOUNT_DIR/etc/systemd/system/hostapd.service"  # Remove mask if exists
ln -sf /lib/systemd/system/hostapd.service "$WANTS/hostapd.service" 2>/dev/null || true

# hostapd override: rfkill + reg domain + foreground mode + stale socket cleanup
# Foreground mode fixes 5GHz timing issue where -B races reg domain propagation
mkdir -p "$MOUNT_DIR/etc/systemd/system/hostapd.service.d"
cat > "$MOUNT_DIR/etc/systemd/system/hostapd.service.d/wifry.conf" <<'HAPD_OVERRIDE'
[Service]
Type=simple
ExecStartPre=/usr/sbin/rfkill unblock wlan
ExecStartPre=/usr/sbin/iw reg set US
ExecStartPre=/bin/rm -f /var/run/hostapd/wlan0
ExecStartPre=/bin/sleep 2
ExecStart=
ExecStart=/usr/sbin/hostapd /etc/hostapd/hostapd.conf
HAPD_OVERRIDE

# Enable dnsmasq
ln -sf /lib/systemd/system/dnsmasq.service "$WANTS/dnsmasq.service" 2>/dev/null || true

echo "Systemd services installed and enabled."

# ─── Step 7: Create first-boot script ────────────────────────────────

echo "Creating first-boot script..."

cat > "$INSTALL_DIR/setup/first-boot.sh" <<'FIRSTBOOT'
#!/bin/bash
# WiFry first-boot script — runs once on the real RPi hardware
# Installs packages that can't be done during image build (need native ARM + network)

MARKER="/var/lib/wifry/.first-boot-complete"
if [ -f "$MARKER" ]; then
    exit 0
fi

exec > /var/log/wifry-first-boot.log 2>&1
echo "WiFry first boot starting at $(date)"

# Wait for network
for i in $(seq 1 30); do
    if ping -c 1 -W 2 8.8.8.8 &>/dev/null; then
        echo "Network ready."
        break
    fi
    echo "Waiting for network... ($i/30)"
    sleep 2
done

# CRITICAL: Sync clock via NTP before anything else
# RPi has no battery-backed RTC — clock is wrong on first boot
# Wrong clock = SSL certs "not yet valid" = apt/pip/curl all fail
echo "Syncing system clock..."
# Try timedatectl first (systemd)
timedatectl set-ntp true 2>/dev/null || true
# Force immediate NTP sync
systemctl restart systemd-timesyncd 2>/dev/null || true
# Wait for clock to sync (check if year is reasonable)
for i in $(seq 1 15); do
    YEAR=$(date +%Y)
    if [ "$YEAR" -ge 2025 ]; then
        echo "Clock synced: $(date)"
        break
    fi
    echo "Waiting for clock sync... (currently $(date))"
    sleep 2
done
# Last resort: use HTTP date header
if [ "$(date +%Y)" -lt 2025 ]; then
    echo "NTP failed, using HTTP date header..."
    HTTP_DATE=$(curl -sI https://google.com 2>/dev/null | grep -i "^date:" | cut -d' ' -f2-)
    if [ -n "$HTTP_DATE" ]; then
        date -s "$HTTP_DATE" 2>/dev/null || true
    fi
fi
echo "Current time: $(date)"

# Install system packages (noninteractive to suppress prompts like iperf3 daemon question)
echo "Installing system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt --fix-broken install -y 2>/dev/null || true
apt-get install -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" \
    python3-venv hostapd dnsmasq bridge-utils iptables \
    tshark wireless-tools iw ffmpeg v4l-utils \
    hping3 iperf3 wireguard-tools openvpn curl jq

# Enable dnsmasq conf-dir (freshly installed dnsmasq has it commented out)
if [ -f /etc/dnsmasq.conf ]; then
    sed -i 's/^#conf-dir=\/etc\/dnsmasq.d$/conf-dir=\/etc\/dnsmasq.d/' /etc/dnsmasq.conf
fi

# Install binary dependencies
ARCH=$(dpkg --print-architecture)

if ! command -v cloudflared &>/dev/null; then
    echo "Installing cloudflared..."
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}" -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
fi

if ! command -v coredns &>/dev/null; then
    echo "Installing CoreDNS..."
    curl -sL "https://github.com/coredns/coredns/releases/download/v1.11.3/coredns_1.11.3_linux_${ARCH}.tgz" | tar xz -C /usr/local/bin/
    chmod +x /usr/local/bin/coredns
fi

if ! command -v speedtest &>/dev/null; then
    echo "Installing Ookla Speedtest..."
    curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash 2>/dev/null
    apt-get install -y -qq speedtest 2>/dev/null || true
fi

# Create wifry user
if ! id wifry &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin wifry
    usermod -aG netdev wifry
fi

# Fix ownership
chown -R wifry:wifry /opt/wifry /var/lib/wifry /var/log/wifry
# tshark/dumpcap drops privileges — captures dir must be world-writable
chmod 1777 /var/lib/wifry/captures
# Add wifry to wireshark group for dumpcap access
usermod -aG wireshark wifry 2>/dev/null || true

# Python venv + pip install (native ARM, SSL works)
echo "Setting up Python environment..."
sudo -u wifry python3 -m venv /opt/wifry/backend/.venv
sudo -u wifry /opt/wifry/backend/.venv/bin/pip install --upgrade pip -q
sudo -u wifry /opt/wifry/backend/.venv/bin/pip install -r /opt/wifry/backend/requirements.txt -q

# Set up NAT/iptables
echo "Configuring NAT..."
iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
iptables -A FORWARD -i wlan0 -o eth0 -j ACCEPT
iptables -A FORWARD -i eth0 -o wlan0 -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables-save > /etc/iptables.rules
cat > /etc/network/if-pre-up.d/iptables <<'EOF'
#!/bin/sh
iptables-restore < /etc/iptables.rules
EOF
chmod +x /etc/network/if-pre-up.d/iptables

# Mark complete
touch "$MARKER"
echo "WiFry first boot complete at $(date)"

# Unblock WiFi radio (RPi OS ships with it soft-blocked)
rfkill unblock wlan 2>/dev/null || true

# Set regulatory domain for 5GHz support (must be before hostapd starts)
iw reg set US 2>/dev/null || true
echo "REGDOMAIN=US" > /etc/default/crda 2>/dev/null || true

# Disable wpa_supplicant (conflicts with hostapd AP mode)
systemctl stop wpa_supplicant 2>/dev/null || true
systemctl disable wpa_supplicant 2>/dev/null || true

# Set static IP on wlan0 for AP
ip addr flush dev wlan0 2>/dev/null || true
ip addr add 192.168.4.1/24 dev wlan0 2>/dev/null || true
ip link set wlan0 up 2>/dev/null || true

# Restart services
systemctl restart hostapd dnsmasq wifry-backend wifry-frontend
FIRSTBOOT
chmod +x "$INSTALL_DIR/setup/first-boot.sh"

# Create systemd service for first boot
cat > "$MOUNT_DIR/etc/systemd/system/wifry-first-boot.service" <<'FBSVC'
[Unit]
Description=WiFry First Boot Setup
After=network-online.target
Wants=network-online.target
Before=wifry-backend.service
ConditionPathExists=!/var/lib/wifry/.first-boot-complete

[Service]
Type=oneshot
ExecStart=/opt/wifry/setup/first-boot.sh
RemainAfterExit=yes
TimeoutStartSec=600

[Install]
WantedBy=multi-user.target
FBSVC

ln -sf /etc/systemd/system/wifry-first-boot.service "$WANTS/wifry-first-boot.service"

echo "First-boot service created."

# ─── Step 8: Unmount and compress ────────────────────────────────────

echo "Unmounting..."
sync
umount "$MOUNT_DIR/boot/firmware"
umount "$MOUNT_DIR"
losetup -d "$LOOP_DEV"

echo "Compressing image (this takes a few minutes)..."
FINAL_NAME="wifry-${VERSION}-rpi-arm64.img.xz"
xz -T0 -9 "$WORK_IMAGE"
mv "${WORK_IMAGE}.xz" "$OUTPUT_DIR/$FINAL_NAME"

# Generate checksum
cd "$OUTPUT_DIR"
sha256sum "$FINAL_NAME" > "$FINAL_NAME.sha256"
SIZE=$(du -sh "$FINAL_NAME" | awk '{print $1}')

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║  Image Build Complete!                       ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
echo "  Image:  $OUTPUT_DIR/$FINAL_NAME"
echo "  Size:   $SIZE"
echo "  SHA256: $(cat "$FINAL_NAME.sha256" | awk '{print $1}')"
echo ""
echo "  Flash to SD card:"
echo "    Use Raspberry Pi Imager → 'Use custom' → select $FINAL_NAME"
echo ""
echo "  Or manually:"
echo "    xz -d $FINAL_NAME"
echo "    sudo dd if=wifry-${VERSION}-rpi-arm64.img of=/dev/sdX bs=4M status=progress"
echo ""
echo "  First boot (with Ethernet connected):"
echo "    - ~5 min to install packages and configure"
echo "    - WiFi SSID 'WiFry' appears when ready"
echo "    - SSH: pi@wifry.local (password: wifry)"
echo ""
