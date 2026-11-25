# Contributing to Solis Inverter Exporter

Install the Python dependencies with `python -m pip install -r requirements.txt` in an isolated environment. Start from [`config.example.yaml`](config.example.yaml) and follow the [README](README.md) to run the exporter. The default metrics endpoint is `http://localhost:9121/metrics`.

## Review a change

- Use representative responses from a fixture to check metric names, units, scaling, and values. Include responses with missing fields and a timeout when changing the polling code.
- Preserve existing metric behavior where possible. If a name or unit changes, show how an existing Prometheus query or Grafana panel should be updated.
- For changes affecting container startup, health, or configuration, validate the affected route in [`compose.yaml`](compose.yaml).

Include the inverter model or fixture, the exporter configuration relevant to the issue, and a short sanitized scrape.
