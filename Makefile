.PHONY: dev backend frontend install test test-coverage build deploy deploy-ssh update-ssh restart-ssh logs-ssh status-ssh verify-ssh ci-backend ci-backend-release-risk ci-frontend ci-deploy-smoke ci-release

# ─── Development (local Mac) ─────────────────────────────────────────

dev:
	@echo "Starting backend (port 8080) and frontend dev server (port 3000)..."
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

ci-backend:
	cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest tests/ --ignore=tests/hw -q --tb=short

ci-backend-release-risk:
	cd backend && source .venv/bin/activate && WIFRY_MOCK_MODE=true python -m pytest \
		tests/test_runtime_state_boundaries.py \
		tests/test_storage_scheduler.py \
		tests/test_sessions.py \
		tests/test_captures.py \
		tests/test_sharing.py \
		tests/test_system.py \
		tests/test_system_extended.py \
		-q

ci-frontend:
	cd frontend && npm run lint && npm test && npx tsc --noEmit && npm run build

ci-deploy-smoke:
	bash -n setup/install.sh setup/wifry-recovery.sh image-build/build-image.sh
	python3 tools/validate_release_paths.py

ci-release: ci-backend ci-backend-release-risk ci-frontend ci-deploy-smoke

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
		sudo rm -rf /opt/wifry/frontend/dist && \
		sudo mkdir -p /opt/wifry/frontend/dist && \
		sudo rsync -a --delete /tmp/wifry-update/frontend/dist/ /opt/wifry/frontend/dist/ && \
		sudo chown -R wifry:wifry /opt/wifry && \
		sudo systemctl restart wifry-backend && \
		rm -rf /tmp/wifry-update"
	@echo "Update deployed and services restarted."

# Run install directly on the RPi (if you're SSH'd in)
deploy:
	sudo bash setup/install.sh

restart-ssh:
	ssh $(RPI) "sudo systemctl restart wifry-backend hostapd dnsmasq"

logs-ssh:
	ssh -t $(RPI) "sudo journalctl -u wifry-backend -u hostapd -u dnsmasq -f"

status-ssh:
	ssh $(RPI) "sudo systemctl status wifry-backend hostapd dnsmasq --no-pager"

verify-ssh:
	ssh $(RPI) "curl -sf http://localhost:8080/api/v1/health && echo ' Backend OK' || echo ' Backend FAIL'"
	ssh $(RPI) "curl -sf http://localhost:8080/ | grep -qi '<!doctype html>' && echo ' Frontend OK' || echo ' Frontend FAIL'"
	ssh $(RPI) "curl -sf http://localhost:8080/api/v1/system/dependencies | python3 -m json.tool"
