# Solis Inverter Exporter ☀️📈

Prometheus exporter for **Solis inverters** using the local web interface (`/status.html`).

It polls the inverter on your LAN on an interval and exposes metrics on `/metrics`.  
Prometheus scraping does **not** trigger extra requests. The exporter serves cached values until the next poll cycle.

<p align="center">
  <img src="images/metrics.png" alt="Grafana example" width="800"/>
</p>

## Features 📊

- Metrics on `/metrics`
- Multi-inverter support
- Parallel polling (`max_parallel`)
- Cached values
- Stale handling for night time offline inverters
  - after `stale_seconds`, power is forced to `0`
  - still keeps last energy counters
- Extra optional info
  - Network info as labels (SSID, IP, MAC, mode)
  - Device info as labels (serial, versions)
- Health and readiness endpoints
  - `/-/healthy` (or `/healthz`)
  - `/-/ready` (or `/readyz`)

## Requirements

- Python 3.10+ (3.11 recommended)
- Or Docker
- LAN access to the inverter web UI
- Inverter web credentials (HTTP auth, Basic/Digest depending on device)

## Install ⚙️

Before you run the exporter, edit `config.yaml` and set:
- your inverter `host`, `username`, `password`
- optional polling settings

## Python 🐍

Install dependencies:

```bash
pip install -r requirements.txt
```

Run (it will look for `config.yaml` in the current folder):

```bash
python solis_inverter_exporter.py
```

Optional:

```bash
python solis_inverter_exporter.py --config-file /path/to/config.yaml
```

Test:

```bash
curl http://localhost:9121/metrics
```

## Docker 🐳 (GHCR)

The image is published to GitHub Container Registry.

Run (mount your `config.yaml`):

```bash
docker run -d \
  --name solis-inverter-exporter \
  -p 9121:9121 \
  -v "$(pwd)/config.yaml:/config/config.yaml:ro" \
  --restart unless-stopped \
  ghcr.io/luizbizzio/solis-inverter-exporter:latest \
  --config-file /config/config.yaml
```

Test:

```bash
curl http://localhost:9121/metrics
```

Notes:
- If you change `server.port`, update the `-p` mapping too.
- The container is stateless. Any config change needs a container restart.
- The exporter reads config from `/config/config.yaml` by default inside Docker.

## Configuration 🛠️

Edit `config.yaml`:

```yaml
server:
  host: "0.0.0.0"
  port: 9121
  expose_default_metrics: false
  log_level: INFO

scrape:
  poll_interval_seconds: 30
  timeout_seconds: 10
  retries: 3
  retry_backoff_seconds: 1
  max_parallel: 4
  stale_seconds: 300

features:
  network_info: true
  device_info: true

solis:
  - name: inverter-1
    host: "IP_ADDRESS"
    username: "INVERTER_USERNAME"
    password: "INVERTER_PASSWORD"
    scheme: "http"
    path: "/status.html"
```

Config notes:
- `stale_seconds: 300` (5 minutes) is a good default for night time offline.
- `expose_default_metrics: true` will also expose `python_*` and `process_*` metrics.
- `features.network_info` and `features.device_info` add label-heavy metrics. Disable if you do not want SSID, MAC, IP in Prometheus.

## Endpoints

- Metrics: `/metrics`
- Health: `/-/healthy` (or `/healthz`)
- Ready: `/-/ready` (or `/readyz`)

## Prometheus scrape config

```yaml
scrape_configs:
  - job_name: "solis-inverter"
    static_configs:
      - targets: ["YOUR_EXPORTER_IP:9121"]
```

## Metrics

Main metrics:

| Name | Type | Description |
|---|---|---|
| `solis_inverter_up` | Gauge | 1 if last poll succeeded, else 0 |
| `solis_inverter_power_watts` | Gauge | Current AC power (W). Forced to 0 after stale |
| `solis_inverter_energy_today_kwh` | Gauge | Energy today (kWh) |
| `solis_inverter_energy_total_kwh` | Gauge | Total energy (kWh) |
| `solis_inverter_stale` | Gauge | 1 if data is stale, else 0 |
| `solis_inverter_last_success_age_seconds` | Gauge | Seconds since last success (-1 if never) |
| `solis_inverter_errors_total` | Counter | Total poll errors |
| `solis_inverter_scrape_duration_seconds` | Gauge | Duration of last poll |
| `solis_inverter_last_success_timestamp` | Gauge | Unix timestamp of last success |
| `solis_inverter_last_attempt_timestamp` | Gauge | Unix timestamp of last attempt |

Optional extra metrics (if available on your inverter page):
- `solis_inverter_rated_power_watts`
- `solis_inverter_uptime_seconds`
- `solis_inverter_alarm_present`
- `solis_remote_status_a`, `solis_remote_status_b`, `solis_remote_status_c`
- `solis_sta_rssi_percent`

Label info metrics (can be disabled in `features`):
- `solis_inverter_network_info{inverter,wmode,ap_ssid,ap_ip,ap_mac,sta_ssid,sta_ip,sta_mac} 1`
- `solis_inverter_device_info{inverter,sn,msvn,ssvn,pv_type,cover_mid,cover_ver} 1`

## Troubleshooting 🔍

If `solis_inverter_up = 0`:
- Check IP and that the inverter web UI is reachable.
- Confirm username and password.
- Try opening `http://INVERTER_IP/status.html` in a browser from the same network.
- Increase `scrape.timeout_seconds` if your inverter is slow.

If power becomes `0` at night:
- That is expected if the inverter goes offline.
- Power is forced to `0` only after `stale_seconds` since last success.

If you do not want SSID, MAC, IP in Prometheus:
- Set `features.network_info: false`
- Set `features.device_info: false`

## Security notice ⚠️

This exporter needs inverter web credentials in `config.yaml`. Treat them as secrets.

Also, `network_info` can expose SSID, IP and MAC addresses as Prometheus labels. Disable it if you do not want that data stored in your monitoring system.

## License

This project is licensed under the [PolyForm Noncommercial License 1.0.0](./LICENSE).
