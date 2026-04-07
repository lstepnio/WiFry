#!/usr/bin/env bash
#
# WiFry login banner / MOTD
# Displays current network settings and recovery instructions on every login.
# Install to: /etc/profile.d/wifry-motd.sh
#

CYAN='\033[0;36m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}  WiFry - IP Video Edition${NC}"
echo -e "${CYAN}  ════════════════════════${NC}"
echo ""

# WiFi
SSID=$(grep "^ssid=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
PASS=$(grep "^wpa_passphrase=" /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2)
AP_IP=$(ip -4 addr show wlan0 2>/dev/null | grep "inet " | head -1 | awk '{print $2}' | cut -d/ -f1)
echo -e "  WiFi:     SSID=${BOLD}${SSID:-WiFry}${NC}  Password=${BOLD}${PASS:-wifry1234}${NC}"
echo -e "  WiFi IP:  ${AP_IP:-192.168.4.1}"

# Ethernet
ETH_IP=$(ip -4 addr show eth0 2>/dev/null | grep "inet " | grep -v "fallback" | head -1 | awk '{print $2}' | cut -d/ -f1)
echo -e "  Ethernet: ${ETH_IP:-(no IP)}"
echo -e "  Fallback: ${GREEN}169.254.42.1${NC} (always reachable)"
echo ""
echo -e "  Web UI:   ${CYAN}http://${AP_IP:-192.168.4.1}:8080${NC} (WiFi)"
[[ -n "$ETH_IP" ]] && echo -e "            ${CYAN}http://${ETH_IP}:8080${NC} (Ethernet)"
echo -e "            ${CYAN}http://169.254.42.1:8080${NC} (Fallback)"
echo ""
echo -e "  ${YELLOW}Recovery console: press Alt+F2${NC}"
echo -e "  ${YELLOW}Or run: sudo /opt/wifry/setup/wifry-recovery.sh${NC}"
echo ""
