# WiFry Operator Runbooks

These runbooks are written for the person installing, updating, recovering, and securing WiFry boxes. They are based on the current repo state: production uses a single `wifry-backend` service on port `8080` to serve both the API and the built frontend.

The command examples below use `pi@wifry.local`. Substitute your actual Pi hostname or IP if mDNS is not available.

## Install a Fresh Box

### Recommended: deploy from a laptop

```bash
make build
make deploy-ssh RPI=pi@wifry.local
```

What this does:

- builds the frontend locally
- syncs the repo to the Pi
- runs `setup/install.sh`
- installs `wifry-backend`, `wifry-recovery`, `hostapd`, and `dnsmasq`

### Direct install on the Pi

```bash
git clone <repo-url> /tmp/wifry
cd /tmp/wifry
sudo bash setup/install.sh
```

### Verify the box came up

```bash
ssh pi@wifry.local "sudo systemctl status wifry-backend hostapd dnsmasq --no-pager"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/health"
```

Expected access paths:

- WiFi AP: [http://192.168.4.1:8080](http://192.168.4.1:8080)
- Ethernet fallback: [http://169.254.42.1:8080](http://169.254.42.1:8080)

## Update an Existing Box

### Supported release update from the UI

Use `System > App Settings > Update` to fetch tags and apply a selected release. The updater checks out the chosen tag in `/opt/wifry`, rebuilds dependencies, writes `VERSION`, and restarts the backend.

### Development update from a laptop

```bash
make update-ssh RPI=pi@wifry.local
```

This is for rapid iteration, not for release management.

### Verify after update

```bash
ssh pi@wifry.local "cat /opt/wifry/VERSION"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/health"
ssh pi@wifry.local "sudo journalctl -u wifry-backend -n 50 --no-pager"
```

## Recover a Locked-Out Box

### Fastest path: fallback Ethernet IP

1. Plug a laptop directly into the Pi Ethernet port
2. Browse to [http://169.254.42.1:8080](http://169.254.42.1:8080)

This fallback IP is intended to remain reachable even if the normal uplink configuration is bad.

### Physical recovery console

1. Attach HDMI + keyboard
2. Press `Alt+F2`
3. Use the recovery menu from `setup/wifry-recovery.sh`

### SSH recovery

```bash
ssh pi@wifry.local "sudo /opt/wifry/setup/wifry-recovery.sh"
```

### Service-level recovery

```bash
ssh pi@wifry.local "sudo systemctl restart wifry-backend hostapd dnsmasq"
ssh pi@wifry.local "sudo journalctl -u wifry-backend -u hostapd -u dnsmasq -n 100 --no-pager"
```

There is no separate `wifry-frontend` service in the current runtime model. If an older note mentions it, use `wifry-backend` instead.

## Security Checklist

### Change defaults before field use

- change the WiFi SSID and WiFi password
- use SSH keys or otherwise rotate any default device credentials
- if you enable a web UI password, set it from the appliance settings before exposing the box beyond a trusted lab

### Keep risky surfaces off unless needed

- leave live remote access and collaboration disabled unless you are actively troubleshooting
- treat scenario APIs as automation-only, not as a primary operator workflow

### Protect secrets

- do not commit API keys to the repo
- keep local secrets in `backend/.env`
- review runtime secrets/settings on the appliance before handing a box to another team

### Review diagnostics

```bash
ssh pi@wifry.local "sudo journalctl -u wifry-backend -u hostapd -u dnsmasq -n 200 --no-pager"
curl -s http://wifry.local:8080/api/v1/system/audit | python3 -m json.tool
```

Session bundles are for STB/test evidence. Use logs, audit events, and box-level diagnostics for WiFry appliance support.

## Install/Update Troubleshooting

### Installer completed but UI is missing

```bash
ssh pi@wifry.local "test -f /opt/wifry/frontend/dist/index.html && echo ok"
ssh pi@wifry.local "sudo systemctl status wifry-backend --no-pager"
ssh pi@wifry.local "curl -sf http://localhost:8080/api/v1/health"
```

### Network stack looks unhealthy

```bash
ssh pi@wifry.local "sudo systemctl status hostapd dnsmasq --no-pager"
ssh pi@wifry.local "ip addr show wlan0"
ssh pi@wifry.local "ip addr show eth0"
```

### Need logs for a human handoff

```bash
curl -s "http://wifry.local:8080/api/v1/system/logs?lines=200" | python3 -m json.tool
curl -s http://wifry.local:8080/api/v1/system/audit | python3 -m json.tool
```
