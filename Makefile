.PHONY: dev backend frontend install test test-coverage build deploy deploy-ssh restart-ssh logs-ssh status-ssh

# ─── Development (local Mac) ─────────────────────────────────────────

dev:
	@echo "Starting backend (port 8080) and frontend (port 3000)..."
	@make backend &
	@make frontend

backend:
	cd backend && source .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8080

frontend:
	cd frontend && npm run dev

install:
	cd backend && python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
	cd frontend && npm install

test:
	cd backend && source .venv/bin/activate && python -m pytest tests/ -v

test-coverage:
	cd backend && source .venv/bin/activate && python -m coverage run -m pytest tests/ -q && python -m coverage report --sort=cover

build:
	cd frontend && npm run build

# ─── Deployment to Raspberry Pi ──────────────────────────────────────
#
# Recommended workflow:
#   1. Build frontend on your laptop (fast):  make build
#   2. Deploy to RPi (includes pre-built frontend): make deploy-ssh RPI=pi@<ip>
#
# This avoids the slow npm build on the RPi itself.

RPI ?= pi@raspberrypi.local

# Deploy to RPi: build frontend locally, sync code + dist, run install
deploy-ssh:
	@echo "Building frontend locally first..."
	cd frontend && npm run build
	@echo ""
	@echo "Syncing to $(RPI):/tmp/wifry-deploy..."
	rsync -avz --progress \
		--exclude '.venv' \
		--exclude 'node_modules' \
		--exclude '__pycache__' \
		--exclude '.pytest_cache' \
		--exclude '.git' \
		./ $(RPI):/tmp/wifry-deploy/
	@echo ""
	@echo "Running install on $(RPI)..."
	ssh -t $(RPI) "sudo bash /tmp/wifry-deploy/setup/install.sh"
	@echo ""
	@echo "Cleaning up..."
	ssh $(RPI) "rm -rf /tmp/wifry-deploy"
	@echo "Deploy complete!"

# Quick code update (skip full install, just sync and restart)
update-ssh:
	@echo "Building frontend..."
	cd frontend && npm run build
	@echo "Syncing code..."
	rsync -avz --progress \
		--exclude '.venv' --exclude 'node_modules' --exclude '__pycache__' --exclude '.git' \
		./ $(RPI):/tmp/wifry-update/
	ssh $(RPI) "sudo rsync -a --delete \
		--exclude '.venv' --exclude 'node_modules' \
		/tmp/wifry-update/ /opt/wifry/ && \
		sudo cp -r /tmp/wifry-update/frontend/dist /opt/wifry/frontend/dist && \
		sudo chown -R wifry:wifry /opt/wifry && \
		sudo systemctl restart wifry-backend wifry-frontend && \
		rm -rf /tmp/wifry-update"
	@echo "Update deployed and services restarted."

# Run install directly on the RPi (if you're SSH'd in)
deploy:
	sudo bash setup/install.sh

restart-ssh:
	ssh $(RPI) "sudo systemctl restart wifry-backend wifry-frontend"

logs-ssh:
	ssh -t $(RPI) "sudo journalctl -u wifry-backend -u wifry-frontend -f"

status-ssh:
	ssh $(RPI) "sudo systemctl status wifry-backend wifry-frontend hostapd dnsmasq --no-pager"

verify-ssh:
	ssh $(RPI) "curl -sf http://localhost:8080/api/v1/health && echo ' Backend OK' || echo ' Backend FAIL'"
	ssh $(RPI) "curl -sf http://localhost:8080/api/v1/system/dependencies | python3 -m json.tool"
