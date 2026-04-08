#!/usr/bin/env bash
#
# WiFry - IP Video Edition
# First-time setup script for Raspberry Pi OS (Bookworm, 64-bit)
#
# Prerequisites:
#   - Raspberry Pi 4B+ or 5 with Raspberry Pi OS Bookworm (64-bit)
#   - Ethernet connected to your upstream network (internet access)
#   - WiFi interface available (built-in or USB adapter)
#
# Usage:
#   Method 1 (recommended): Deploy from your laptop
#     make deploy-ssh RPI=pi@<rpi-ip>
#
#   Method 2: Run directly on the RPi
#     git clone <repo-url> /tmp/wifry && cd /tmp/wifry && sudo bash setup/install.sh
#
#   Method 3: Pre-built (if available)
#     Download wifry-rpi-image.img.xz, flash to SD card, boot
#
set -euo pipefail

INSTALL_DIR="/opt/wifry"
DATA_DIR="/var/lib/wifry"
WIFRY_USER="wifry"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

info()  { echo -e "${GREEN}[WiFry]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WiFry]${NC} $*"; }
error() { echo -e "${RED}[WiFry]${NC} $*" >&2; }
step()  { echo -e "\n${CYAN}${BOLD}── $* ──${NC}"; }

sync_frontend_dist() {
    local src_dir="$1"
    local dest_dir="$INSTALL_DIR/frontend/dist"

    rm -rf "$dest_dir"
    mkdir -p "$dest_dir"
    rsync -a --delete "$src_dir/" "$dest_dir/"
    chown -R "$WIFRY_USER:$WIFRY_USER" "$dest_dir"
}

# Track timing
START_TIME=$(date +%s)

# ─── Pre-flight checks ───────────────────────────────────────────────

step "Pre-flight checks"

if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root (use sudo)"
    exit 1
fi

# Check architecture
ARCH=$(dpkg --print-architecture 2>/dev/null || uname -m)
info "Architecture: $ARCH"

if [[ "$ARCH" != "arm64" && "$ARCH" != "aarch64" && "$ARCH" != "armhf" ]]; then
    warn "Expected ARM architecture, got $ARCH. Continuing anyway..."
fi

# Check for RPi
if grep -q "Raspberry Pi" /proc/device-tree/model 2>/dev/null; then
    RPI_MODEL=$(cat /proc/device-tree/model | tr -d '\0')
    info "Device: $RPI_MODEL"
else
    warn "Not detected as Raspberry Pi. Continuing anyway..."
fi

# Check internet
if ! ping -c 1 -W 3 8.8.8.8 &>/dev/null; then
    error "No internet access. Connect Ethernet to your upstream network first."
    exit 1
fi
info "Internet: connected"

# Check WiFi interface
WLAN_IFACE=$(iw dev 2>/dev/null | awk '/Interface/{print $2}' | head -1)
WLAN_IFACE=${WLAN_IFACE:-wlan0}
if ip link show "$WLAN_IFACE" &>/dev/null; then
    info "WiFi interface: $WLAN_IFACE"
else
    warn "WiFi interface $WLAN_IFACE not found. Hotspot features may not work."
fi

# Check upstream interface
UPSTREAM_IFACE=$(ip route | awk '/default/{print $5}' | head -1)
UPSTREAM_IFACE=${UPSTREAM_IFACE:-eth0}
info "Upstream interface: $UPSTREAM_IFACE"

info "Starting WiFry installation..."

# ─── System packages ─────────────────────────────────────────────────

step "Installing system packages"

apt-get update -qq

apt-get install -y -qq \
    python3 python3-venv python3-pip \
    hostapd dnsmasq bridge-utils \
    iproute2 iptables iptables-persistent \
    tshark libcap2-bin wireless-tools iw \
    nodejs npm git \
    ffmpeg v4l-utils \
    hping3 iperf3 \
    wireguard-tools openvpn \
    strongswan strongswan-swanctl \
    curl jq rsync \
    unattended-upgrades apt-listchanges rpi-eeprom

info "System packages installed."

# Grant dumpcap raw capture capability (avoids running as root)
setcap cap_net_raw,cap_net_admin=eip /usr/bin/dumpcap 2>/dev/null || true
info "dumpcap capabilities set."

step "Upgrading system packages"

apt-get dist-upgrade -y -qq -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold"
apt-get autoremove -y -qq
info "System packages upgraded."

step "Updating RPi firmware"

rpi-eeprom-update -a 2>/dev/null || warn "RPi firmware update skipped (not available on this platform)"

step "Configuring automatic security updates"

export DEBIAN_FRONTEND=noninteractive
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'AUTOUPG'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
AUTOUPG

cat > /etc/apt/apt.conf.d/52wifry-unattended-upgrades <<'UNATTENDED'
Unattended-Upgrade::Origins-Pattern {
    "origin=Debian,codename=${distro_codename},label=Debian-Security";
    "origin=Raspbian,codename=${distro_codename}";
    "origin=Raspberry Pi Foundation,codename=${distro_codename}";
};
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
Unattended-Upgrade::Automatic-Reboot "false";
UNATTENDED

systemctl enable unattended-upgrades 2>/dev/null || true
info "Automatic security updates configured."

# ─── Binary dependencies ─────────────────────────────────────────────

step "Installing binary dependencies"

# Cloudflare Tunnel
if ! command -v cloudflared &>/dev/null; then
    info "Installing cloudflared..."
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${ARCH}" -o /usr/local/bin/cloudflared
    chmod +x /usr/local/bin/cloudflared
else
    info "cloudflared: already installed"
fi

# CoreDNS
if ! command -v coredns &>/dev/null; then
    info "Installing CoreDNS..."
    COREDNS_VER="1.11.3"
    curl -sL "https://github.com/coredns/coredns/releases/download/v${COREDNS_VER}/coredns_${COREDNS_VER}_linux_${ARCH}.tgz" | tar xz -C /usr/local/bin/
    chmod +x /usr/local/bin/coredns
else
    info "CoreDNS: already installed"
fi

# mitmproxy
if ! command -v mitmdump &>/dev/null; then
    info "Installing mitmproxy (this may take a few minutes on RPi)..."
    pip3 install --break-system-packages mitmproxy -q 2>/dev/null || {
        warn "pip install failed, downloading prebuilt binary..."
        MITM_VER="10.4.2"
        if [[ "$ARCH" == "arm64" || "$ARCH" == "aarch64" ]]; then
            curl -sL "https://downloads.mitmproxy.org/${MITM_VER}/mitmproxy-${MITM_VER}-linux-aarch64.tar.gz" | tar xz -C /usr/local/bin/ mitmdump mitmproxy mitmweb
        fi
        chmod +x /usr/local/bin/mitmdump /usr/local/bin/mitmproxy /usr/local/bin/mitmweb 2>/dev/null || true
    }
else
    info "mitmproxy: already installed"
fi

# Ookla Speedtest CLI
if ! command -v speedtest &>/dev/null; then
    info "Installing Ookla Speedtest CLI..."
    curl -s https://packagecloud.io/install/repositories/ookla/speedtest-cli/script.deb.sh | bash 2>/dev/null
    apt-get install -y -qq speedtest 2>/dev/null || warn "Ookla Speedtest CLI install failed (non-critical)"
else
    info "Speedtest CLI: already installed"
fi

# ─── Create user + directories ───────────────────────────────────────

step "Setting up user and directories"

if ! id "$WIFRY_USER" &>/dev/null; then
    useradd --system --create-home --shell /usr/sbin/nologin "$WIFRY_USER"
    info "Created user '$WIFRY_USER'"
fi
usermod -aG netdev "$WIFRY_USER" 2>/dev/null || true
usermod -aG video "$WIFRY_USER" 2>/dev/null || true   # EXPERIMENTAL_VIDEO_CAPTURE — UVC device access

# Create all data directories
for dir in captures reports sessions segments bundles annotations \
           adb-files hdmi-captures coredns teleport network-profiles; do
    mkdir -p "$DATA_DIR/$dir"
done
mkdir -p /var/log/wifry

chown -R "$WIFRY_USER:$WIFRY_USER" "$DATA_DIR"
chown -R "$WIFRY_USER:$WIFRY_USER" /var/log/wifry
info "Directories created."

# ─── Deploy application code ─────────────────────────────────────────

step "Deploying application code"

mkdir -p "$INSTALL_DIR"
rsync -a --delete \
    --exclude '.venv' \
    --exclude 'node_modules' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'dist' \
    --exclude '.git' \
    "$PROJECT_DIR/" "$INSTALL_DIR/"

chown -R "$WIFRY_USER:$WIFRY_USER" "$INSTALL_DIR"
info "Code deployed to $INSTALL_DIR"

# ─── Python environment ──────────────────────────────────────────────

step "Setting up Python environment"

sudo -u "$WIFRY_USER" python3 -m venv "$INSTALL_DIR/backend/.venv"
sudo -u "$WIFRY_USER" "$INSTALL_DIR/backend/.venv/bin/pip" install --upgrade pip -q
sudo -u "$WIFRY_USER" "$INSTALL_DIR/backend/.venv/bin/pip" install -r "$INSTALL_DIR/backend/requirements.txt" -q
info "Python dependencies installed."

# ─── Frontend build ──────────────────────────────────────────────────

step "Building frontend"

# Check if pre-built dist exists (from laptop build)
if [[ -d "$PROJECT_DIR/frontend/dist" ]]; then
    info "Using pre-built frontend from deploy..."
    sync_frontend_dist "$PROJECT_DIR/frontend/dist"
else
    info "Building frontend on RPi (this takes a few minutes)..."
    cd "$INSTALL_DIR/frontend"
    sudo -u "$WIFRY_USER" npm install --production=false --silent 2>/dev/null
    sudo -u "$WIFRY_USER" npm run build
fi
info "Frontend ready."

# ─── Network configuration ───────────────────────────────────────────

step "Configuring network"

# Stop services during config
systemctl stop hostapd 2>/dev/null || true
systemctl unmask hostapd 2>/dev/null || true

# hostapd config
cat > /etc/hostapd/hostapd.conf <<EOF
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
EOF

if [[ -f /etc/default/hostapd ]]; then
    sed -i 's|^#\?DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
fi

# dnsmasq config
if [[ -f /etc/dnsmasq.conf ]]; then
    sed -i 's/^interface=/#interface=/' /etc/dnsmasq.conf
fi

cat > /etc/dnsmasq.d/wifry.conf <<EOF
interface=${WLAN_IFACE}
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.200,255.255.255.0,24h
dhcp-option=6,192.168.4.1
server=8.8.8.8
no-resolv
log-queries
log-dhcp
log-facility=/var/log/wifry-dnsmasq.log
EOF

# Static IP for AP interface
if ! grep -q "# WiFry AP config" /etc/dhcpcd.conf 2>/dev/null; then
    cat >> /etc/dhcpcd.conf <<EOF

# WiFry AP config
interface ${WLAN_IFACE}
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF
fi

# Fallback IP (lockout prevention — always reachable on Ethernet)
info "Setting up fallback IP (169.254.42.1)..."
if ! grep -q "# WiFry fallback" /etc/dhcpcd.conf 2>/dev/null; then
    cat >> /etc/dhcpcd.conf <<EOF

# WiFry fallback — always reachable for recovery
interface ${UPSTREAM_IFACE}
    static ip_address=169.254.42.1/16
    nolink
EOF
fi

# IP forwarding
if ! grep -q "^net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi
sysctl -w net.ipv4.ip_forward=1 >/dev/null

# NAT
info "Setting up NAT ($WLAN_IFACE -> $UPSTREAM_IFACE)..."
iptables -t nat -C POSTROUTING -o "$UPSTREAM_IFACE" -j MASQUERADE 2>/dev/null || \
    iptables -t nat -A POSTROUTING -o "$UPSTREAM_IFACE" -j MASQUERADE

iptables -C FORWARD -i "$WLAN_IFACE" -o "$UPSTREAM_IFACE" -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$WLAN_IFACE" -o "$UPSTREAM_IFACE" -j ACCEPT

iptables -C FORWARD -i "$UPSTREAM_IFACE" -o "$WLAN_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || \
    iptables -A FORWARD -i "$UPSTREAM_IFACE" -o "$WLAN_IFACE" -m state --state RELATED,ESTABLISHED -j ACCEPT

# Persist iptables
netfilter-persistent save 2>/dev/null || {
    iptables-save > /etc/iptables.rules
    cat > /etc/network/if-pre-up.d/iptables <<'IPTEOF'
#!/bin/sh
iptables-restore < /etc/iptables.rules
IPTEOF
    chmod +x /etc/network/if-pre-up.d/iptables
}

info "Network configured."

# ─── Security ────────────────────────────────────────────────────────

step "Configuring security"

install -m 0440 "$INSTALL_DIR/setup/wifry-sudoers" /etc/sudoers.d/wifry
visudo -cf /etc/sudoers.d/wifry || {
    error "Invalid sudoers file! Removing..."
    rm -f /etc/sudoers.d/wifry
    exit 1
}
info "Sudoers rules installed."

# ─── Login banner + Recovery console ─────────────────────────────────

step "Installing system services"

install -m 0644 "$INSTALL_DIR/setup/wifry-motd.sh" /etc/profile.d/wifry-motd.sh

cp "$INSTALL_DIR/setup/wifry-backend.service" /etc/systemd/system/
cp "$INSTALL_DIR/setup/wifry-recovery.service" /etc/systemd/system/

systemctl daemon-reload
systemctl enable wifry-backend.service
systemctl enable wifry-recovery.service
systemctl enable hostapd.service
systemctl enable dnsmasq.service

# ─── Start everything ────────────────────────────────────────────────

step "Starting services"

systemctl restart dhcpcd
sleep 2
systemctl restart hostapd
systemctl restart dnsmasq
systemctl start wifry-backend

# Wait for backend to be ready
info "Waiting for backend to start..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8080/api/v1/health &>/dev/null; then
        break
    fi
    sleep 1
done

# ─── Verification ────────────────────────────────────────────────────

step "Verifying installation"

PASS=0
FAIL=0

check() {
    if eval "$2" &>/dev/null; then
        info "  ✓ $1"
        PASS=$((PASS + 1))
    else
        error "  ✗ $1"
        FAIL=$((FAIL + 1))
    fi
}

check "Backend API responding" "curl -sf http://localhost:8080/api/v1/health"
check "Frontend bundle present" "test -f $INSTALL_DIR/frontend/dist/index.html"
check "Frontend served by backend" "curl -sf http://localhost:8080/ | grep -qi '<!doctype html>'"
check "hostapd running" "systemctl is-active hostapd"
check "dnsmasq running" "systemctl is-active dnsmasq"
check "Backend service enabled" "systemctl is-enabled wifry-backend"
check "Recovery service enabled" "systemctl is-enabled wifry-recovery"
check "WiFi AP IP set" "ip addr show $WLAN_IFACE | grep -q '192.168.4.1'"
check "IP forwarding enabled" "sysctl net.ipv4.ip_forward | grep -q '= 1'"
check "NAT rules set" "iptables -t nat -S | grep -q MASQUERADE"
check "tshark available" "command -v tshark"
check "dumpcap available" "command -v dumpcap"
check "dumpcap has capabilities" "/sbin/getcap /usr/bin/dumpcap | grep -q cap_net_raw"
check "ffmpeg available" "command -v ffmpeg"
check "CoreDNS available" "command -v coredns"
check "Recovery console enabled" "systemctl is-enabled wifry-recovery"

# ─── Done ────────────────────────────────────────────────────────────

END_TIME=$(date +%s)
DURATION=$(( END_TIME - START_TIME ))
MINUTES=$(( DURATION / 60 ))
SECONDS=$(( DURATION % 60 ))

echo ""
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║     WiFry - IP Video Edition                     ║"
echo "  ║     Installation Complete                        ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
info "  Verification: ${PASS} passed, ${FAIL} failed"
info "  Install time: ${MINUTES}m ${SECONDS}s"
echo ""
info "  ${BOLD}WiFi Hotspot${NC}"
info "    SSID:       WiFry"
info "    Password:   wifry1234"
info "    IP:         192.168.4.1"
echo ""
info "  ${BOLD}Web UI${NC}"
info "    WiFi:       http://192.168.4.1:8080"
info "    Ethernet:   http://<rpi-ip>:8080"
info "    Fallback:   http://169.254.42.1:8080"
info "    API docs:   http://<rpi-ip>:8080/docs"
echo ""
info "  ${BOLD}Recovery${NC}"
info "    Console:    Alt+F2 (on attached monitor)"
info "    Script:     sudo /opt/wifry/setup/wifry-recovery.sh"
echo ""
info "  ${BOLD}Services${NC}"
info "    Backend:    systemctl status wifry-backend"
info "    Logs:       journalctl -u wifry-backend -u hostapd -u dnsmasq -f"
echo ""

if [[ $FAIL -gt 0 ]]; then
    warn "  Some checks failed. Run the recovery console (Alt+F2) to troubleshoot."
fi
