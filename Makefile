SHELL := /bin/sh

IMAGE ?= ghcr.io/luizbizzio/solis-inverter-exporter
CONTAINER ?= solis-inverter-exporter
PORT ?= 9121
PYTHON ?= python3
VENV ?= .venv
SCRIPT ?= solis_inverter_exporter.py
CONFIG ?= config.yaml

.PHONY: help venv install run docker-build docker-run docker-stop docker-rm docker-logs docker-pull test

help:
	@printf '%s\n' \
	  'make venv          Create virtual environment' \
	  'make install       Install Python dependencies into .venv' \
	  'make run           Run locally with $(CONFIG)' \
	  'make docker-build  Build local Docker image' \
	  'make docker-run    Run Docker container with $(CONFIG)' \
	  'make docker-stop   Stop container' \
	  'make docker-rm     Remove container' \
	  'make docker-logs   Follow container logs' \
	  'make docker-pull   Pull latest GHCR image' \
	  'make test          Query /metrics locally'

venv:
	$(PYTHON) -m venv $(VENV)

install: venv
	$(VENV)/bin/python -m pip install -U pip
	$(VENV)/bin/pip install -r requirements.txt

run:
	$(PYTHON) $(SCRIPT) --config-file $(CONFIG)

docker-build:
	docker build -t $(IMAGE):latest .

docker-run:
	docker rm -f $(CONTAINER) >/dev/null 2>&1 || true
	docker run -d \
	  --name $(CONTAINER) \
	  -p $(PORT):$(PORT) \
	  -v "$$(pwd)/$(CONFIG):/config/config.yaml:ro" \
	  --restart unless-stopped \
	  $(IMAGE):latest \
	  --config-file /config/config.yaml

docker-stop:
	docker stop $(CONTAINER)

docker-rm:
	docker rm -f $(CONTAINER)

docker-logs:
	docker logs -f $(CONTAINER)

docker-pull:
	docker pull $(IMAGE):latest

test:
	curl http://localhost:$(PORT)/metrics
