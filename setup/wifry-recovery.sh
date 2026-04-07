#!/usr/bin/env bash
#
# WiFry Recovery Console
#
# Run this on the RPi's local console (HDMI + keyboard) to recover
# from any lockout. No network access required.
#
# Auto-starts on tty2 via systemd. Switch to it with: Alt+F2
# Or run manually: sudo /opt/wifry/setup/wifry-recovery.sh
#
set -euo pipefail

INSTALL_DIR="/opt/wifry"
CONFIG_PATH="/var/lib/wifry/network_config.json"
FALLBACK_IP="169.254.42.1"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

clear_screen() {
    clear
    echo -e "${CYAN}${BOLD}"
    echo "  ╔══════════════════════════════════════════════╗"
    echo "  ║     WiFry - IP Video Edition                 ║"
    echo "  ║     Recovery Console                         ║"
    echo "  ╚══════════════════════════════════════════════╝"
    echo -e "${NC}"
}

show_status() {
    echo -e "${BOLD}Current Network Settings:${NC}"
    echo ""

    # WiFi AP
    if systemctl is-active --quiet hostapd 2>/dev/null; then
        SSID=$(grep "^ssid=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
        PASS=$(grep "^wpa_passphrase=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
        CHAN=$(grep "^channel=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
        AP_IP=$(ip -4 addr show wlan0 2>/dev/null | grep "inet " | head -1 | awk '{print $2}' | cut -d/ -f1)
        echo -e "  WiFi AP:    ${GREEN}Running${NC}"
        echo -e "  SSID:       ${BOLD}${SSID:-unknown}${NC}"
        echo -e "  Password:   ${BOLD}${PASS:-unknown}${NC}"
        echo -e "  Channel:    ${CHAN:-auto}"
        echo -e "  AP IP:      ${AP_IP:-192.168.4.1}"
    else
        echo -e "  WiFi AP:    ${RED}Stopped${NC}"
    fi

    echo ""

    # Ethernet
    ETH_IP=$(ip -4 addr show eth0 2>/dev/null | grep "inet " | grep -v "fallback" | head -1 | awk '{print $2}')
    if [[ -n "$ETH_IP" ]]; then
        echo -e "  Ethernet:   ${GREEN}${ETH_IP}${NC}"
    else
        echo -e "  Ethernet:   ${RED}No IP${NC}"
    fi

    GW=$(ip route | grep "^default" | head -1 | awk '{print $3}')
    [[ -n "$GW" ]] && echo -e "  Gateway:    ${GW}"

    DNS=$(grep "^nameserver" /etc/resolv.conf 2>/dev/null | head -1 | awk '{print $2}')
    [[ -n "$DNS" ]] && echo -e "  DNS:        ${DNS}"

    # Fallback IP
    FALLBACK=$(ip -4 addr show eth0:fallback 2>/dev/null | grep "inet " | awk '{print $2}')
    if [[ -n "$FALLBACK" ]]; then
        echo -e "  Fallback:   ${GREEN}${FALLBACK}${NC} (always on)"
    else
        echo -e "  Fallback:   ${YELLOW}Not set${NC} — use option 7 to fix"
    fi

    echo ""
    echo -e "${BOLD}Services:${NC}"

    for SVC in wifry-backend hostapd dnsmasq; do
        if systemctl is-active --quiet "$SVC" 2>/dev/null; then
            echo -e "  ${SVC}: ${GREEN}running${NC}"
        else
            echo -e "  ${SVC}: ${RED}stopped${NC}"
        fi
    done

    echo ""
    echo -e "${BOLD}Access the Web UI:${NC}"
    echo -e "  ${CYAN}http://${FALLBACK_IP}:8080${NC}  (fallback — always works via Ethernet cable)"
    if [[ -n "$ETH_IP" ]]; then
        IP_ONLY=$(echo "$ETH_IP" | cut -d/ -f1)
        echo -e "  ${CYAN}http://${IP_ONLY}:8080${NC}  (ethernet)"
    fi
    AP_IP=${AP_IP:-192.168.4.1}
    echo -e "  ${CYAN}http://${AP_IP}:8080${NC}   (WiFi — connect to SSID above)"
    echo ""
}

reset_network_defaults() {
    echo -e "${YELLOW}Resetting network to safe defaults...${NC}"
    echo ""

    # Stop hostapd to release wlan0
    systemctl stop hostapd 2>/dev/null || true

    # Write default hostapd config
    cat > /etc/hostapd/hostapd.conf <<'EOF'
interface=wlan0
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

    # Write default dnsmasq config
    cat > /etc/dnsmasq.d/wifry.conf <<'EOF'
interface=wlan0
bind-interfaces
dhcp-range=192.168.4.10,192.168.4.200,255.255.255.0,24h
dhcp-option=6,192.168.4.1
server=8.8.8.8
no-resolv
EOF

    # Set AP IP
    ip addr flush dev wlan0 2>/dev/null || true
    ip addr add 192.168.4.1/24 dev wlan0 2>/dev/null || true
    ip link set wlan0 up 2>/dev/null || true

    # Ensure fallback IP
    ip addr add ${FALLBACK_IP}/16 dev eth0 label eth0:fallback 2>/dev/null || true

    # Reset Ethernet to DHCP
    systemctl restart dhcpcd 2>/dev/null || true

    # Enable IP forwarding
    sysctl -w net.ipv4.ip_forward=1 > /dev/null

    # Restart services
    systemctl restart hostapd 2>/dev/null || true
    systemctl restart dnsmasq 2>/dev/null || true

    # Reset saved config to first_boot
    cat > "$CONFIG_PATH" <<'EOF'
{
  "wifi_ap": {
    "ssid": "WiFry", "password": "wifry1234", "channel": 6, "band": "2.4GHz",
    "hidden": false, "ip": "192.168.4.1", "netmask": "255.255.255.0",
    "dhcp_start": "192.168.4.10", "dhcp_end": "192.168.4.200", "country_code": "US"
  },
  "ethernet": {"mode": "dhcp", "static_ip": "", "static_netmask": "255.255.255.0", "static_gateway": "", "static_dns": "8.8.8.8"},
  "fallback": {"enabled": true, "ip": "169.254.42.1", "netmask": "255.255.0.0"},
  "first_boot": true
}
EOF
    chown wifry:wifry "$CONFIG_PATH" 2>/dev/null || true

    echo ""
    echo -e "${GREEN}Network reset to defaults:${NC}"
    echo -e "  WiFi SSID:     ${BOLD}WiFry${NC}"
    echo -e "  WiFi Password: ${BOLD}wifry1234${NC}"
    echo -e "  WiFi IP:       ${BOLD}192.168.4.1${NC}"
    echo -e "  Ethernet:      ${BOLD}DHCP${NC}"
    echo -e "  Fallback IP:   ${BOLD}${FALLBACK_IP}${NC}"
    echo ""
}

restart_services() {
    echo -e "${YELLOW}Restarting all WiFry services...${NC}"
    systemctl restart hostapd 2>/dev/null || echo "  hostapd: failed"
    systemctl restart dnsmasq 2>/dev/null || echo "  dnsmasq: failed"
    systemctl restart wifry-backend 2>/dev/null || echo "  wifry-backend: failed"
    echo -e "${GREEN}Services restarted.${NC}"
    echo ""
}

set_wifi_ssid() {
    echo -e "${BOLD}Current SSID:${NC} $(grep '^ssid=' /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)"
    read -p "New SSID: " NEW_SSID
    if [[ -n "$NEW_SSID" ]]; then
        sed -i "s/^ssid=.*/ssid=${NEW_SSID}/" /etc/hostapd/hostapd.conf
        echo -e "${GREEN}SSID set to: ${NEW_SSID}${NC}"
        read -p "Restart WiFi AP now? [y/N] " RESTART
        [[ "$RESTART" =~ ^[Yy] ]] && systemctl restart hostapd
    fi
    echo ""
}

set_wifi_password() {
    echo -e "${BOLD}Changing WiFi password...${NC}"
    read -s -p "New password (min 8 chars): " NEW_PASS
    echo ""
    if [[ ${#NEW_PASS} -ge 8 ]]; then
        sed -i "s/^wpa_passphrase=.*/wpa_passphrase=${NEW_PASS}/" /etc/hostapd/hostapd.conf
        echo -e "${GREEN}Password changed.${NC}"
        read -p "Restart WiFi AP now? [y/N] " RESTART
        [[ "$RESTART" =~ ^[Yy] ]] && systemctl restart hostapd
    else
        echo -e "${RED}Password too short (min 8 characters).${NC}"
    fi
    echo ""
}

set_static_ethernet() {
    read -p "Static IP (e.g. 192.168.1.100): " IP
    read -p "Netmask (e.g. 255.255.255.0): " MASK
    read -p "Gateway (e.g. 192.168.1.1): " GW
    read -p "DNS (e.g. 8.8.8.8): " DNS

    if [[ -n "$IP" ]]; then
        ip addr flush dev eth0 2>/dev/null || true
        ip addr add "${IP}/${MASK}" dev eth0 2>/dev/null || true
        [[ -n "$GW" ]] && ip route add default via "$GW" dev eth0 2>/dev/null || true
        [[ -n "$DNS" ]] && echo "nameserver $DNS" > /etc/resolv.conf
        # Re-add fallback
        ip addr add ${FALLBACK_IP}/16 dev eth0 label eth0:fallback 2>/dev/null || true
        echo -e "${GREEN}Static IP set: ${IP}${NC}"
    fi
    echo ""
}

show_logs() {
    echo -e "${BOLD}Recent WiFry logs (last 50 lines):${NC}"
    echo ""
    journalctl -u wifry-backend -u hostapd -u dnsmasq --no-pager -n 50
    echo ""
    read -p "Press Enter to continue..."
}

factory_reset() {
    echo -e "${RED}${BOLD}WARNING: This will reset ALL WiFry data!${NC}"
    echo "  - Network configuration"
    echo "  - All captures, sessions, and artifacts"
    echo "  - All settings (API keys, VPN profiles, etc.)"
    echo ""
    read -p "Type 'RESET' to confirm: " CONFIRM
    if [[ "$CONFIRM" == "RESET" ]]; then
        echo -e "${YELLOW}Performing factory reset...${NC}"
        rm -rf /var/lib/wifry/*
        reset_network_defaults
        restart_services
        echo -e "${GREEN}Factory reset complete.${NC}"
    else
        echo "Cancelled."
    fi
    echo ""
}

# --- Main menu loop ---

while true; do
    clear_screen
    show_status

    echo -e "${BOLD}Recovery Options:${NC}"
    echo ""
    echo "  1) Reset network to safe defaults"
    echo "  2) Restart all services"
    echo "  3) Change WiFi SSID"
    echo "  4) Change WiFi password"
    echo "  5) Set static Ethernet IP"
    echo "  6) Reset Ethernet to DHCP"
    echo "  7) Ensure fallback IP (${FALLBACK_IP})"
    echo "  8) View recent logs"
    echo "  9) Factory reset (wipe all data)"
    echo "  0) Reboot"
    echo "  q) Exit to shell"
    echo ""
    read -p "  Choose [1-9, 0, q]: " CHOICE

    case "$CHOICE" in
        1) reset_network_defaults; read -p "Press Enter to continue..." ;;
        2) restart_services; read -p "Press Enter to continue..." ;;
        3) set_wifi_ssid; read -p "Press Enter to continue..." ;;
        4) set_wifi_password; read -p "Press Enter to continue..." ;;
        5) set_static_ethernet; read -p "Press Enter to continue..." ;;
        6) systemctl restart dhcpcd; echo -e "${GREEN}DHCP restored.${NC}"; sleep 2 ;;
        7) ip addr add ${FALLBACK_IP}/16 dev eth0 label eth0:fallback 2>/dev/null || true; echo -e "${GREEN}Fallback IP active.${NC}"; sleep 2 ;;
        8) show_logs ;;
        9) factory_reset; read -p "Press Enter to continue..." ;;
        0) echo "Rebooting..."; systemctl reboot ;;
        q|Q) echo "Exiting to shell."; exit 0 ;;
        *) echo "Invalid choice."; sleep 1 ;;
    esac
done
