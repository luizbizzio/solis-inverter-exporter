# SPDX-FileCopyrightText: Copyright (c) 2024-2026 Luiz Bizzio
# SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0

import argparse
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
import yaml
from prometheus_client import CollectorRegistry, Counter, Gauge, Info
from prometheus_client.exposition import make_wsgi_app
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer, make_server


DEFAULT_CONFIG_PATH = "config.yaml"
EXPORTER_VERSION = "1.1.1"

VAR_RE = re.compile(r'\bvar\s+([A-Za-z0-9_]+)\s*=\s*"([^"]*)"\s*;')
PCT_RE = re.compile(r"(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class InverterConfig:
    name: str
    url: str
    username: str
    password: str


class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def setup_logging(level: str) -> None:
    lvl = getattr(logging, str(level).upper(), logging.INFO)
    logging.basicConfig(level=lvl, format="%(asctime)s %(levelname)s %(message)s")


def to_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return float(s)
    except Exception:
        return None


def clean_label(value: Optional[str], default: str = "unknown") -> str:
    if value is None:
        return default
    s = str(value).replace("\n", " ").replace("\r", " ").strip()
    return s if s else default


def parse_vars(html: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in VAR_RE.findall(html or ""):
        out[k] = v
    return out


def parse_percent(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    m = PCT_RE.search(s)
    if not m:
        return None
    return to_float(m.group(1))


def parse_status_flag(value: Optional[str]) -> int:
    s = str(value).strip() if value is not None else ""
    if s == "1":
        return 1
    if s == "0":
        return 0
    return -1


def build_inverters(cfg: dict) -> List[InverterConfig]:
    items = cfg.get("solis") or []
    if not isinstance(items, list) or not items:
        raise SystemExit("config.yaml: 'solis' must be a non-empty list")

    used = set()
    out: List[InverterConfig] = []

    for raw in items:
        if not isinstance(raw, dict):
            raise SystemExit("config.yaml: each item in 'solis' must be a map")

        name = str(raw.get("name") or "").strip()
        host = str(raw.get("host") or "").strip()
        username = str(raw.get("username") or "").strip()
        password = str(raw.get("password") or "").strip()
        scheme = str(raw.get("scheme") or "http").strip().lower()
        path = str(raw.get("path") or "/status.html").strip()

        if not host or not username or not password:
            raise SystemExit("config.yaml: each inverter needs host, username, password")

        if not name:
            name = host

        if name in used:
            raise SystemExit(f"config.yaml: duplicate inverter name: {name}")
        used.add(name)

        if not path.startswith("/"):
            path = "/" + path

        url = f"{scheme}://{host}{path}"
        out.append(InverterConfig(name=name, url=url, username=username, password=password))

    return out


class SolisExporter:
    def __init__(self, config_path: str) -> None:
        cfg = load_config(config_path)

        server = cfg.get("server") or {}
        scrape = cfg.get("scrape") or {}
        features = cfg.get("features") or {}

        self.port = int(server.get("port", 8686))
        self.expose_default_metrics = bool(server.get("expose_default_metrics", False))
        self.log_level = str(server.get("log_level", "INFO"))

        self.poll_interval_seconds = int(scrape.get("poll_interval_seconds", 15))
        self.timeout_seconds = int(scrape.get("timeout_seconds", 10))
        self.retries = int(scrape.get("retries", 3))
        self.retry_backoff_seconds = float(scrape.get("retry_backoff_seconds", 1))
        self.max_parallel = int(scrape.get("max_parallel", 4))
        self.stale_seconds = int(scrape.get("stale_seconds", 300))

        self.enable_network_info = bool(features.get("network_info", True))
        self.enable_device_info = bool(features.get("device_info", True))

        setup_logging(self.log_level)

        self.inverters = build_inverters(cfg)

        self._stop = threading.Event()
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._last_success: Dict[str, float] = {}

        self._sessions: Dict[str, requests.Session] = {}
        self._session_locks: Dict[str, threading.Lock] = {}

        for inv in self.inverters:
            self._session_locks[inv.name] = threading.Lock()
            self._sessions[inv.name] = self._new_session(inv)

        self.registry = CollectorRegistry() if not self.expose_default_metrics else None
        metric_kwargs = {} if self.registry is None else {"registry": self.registry}

        self.build_info = Info("solis_inverter_exporter_build_info", "Build info", **metric_kwargs)
        self.build_info.info({"version": EXPORTER_VERSION})

        self.exporter_ready = Gauge(
            "solis_inverter_exporter_ready",
            "1 if exporter has completed at least one poll cycle",
            **metric_kwargs,
        )

        self.inverter_up = Gauge("solis_inverter_up", "1 if last poll succeeded, else 0", ["inverter"], **metric_kwargs)
        self.inverter_last_attempt = Gauge("solis_inverter_last_attempt_timestamp", "Unix timestamp of last poll attempt", ["inverter"], **metric_kwargs)
        self.inverter_last_success = Gauge("solis_inverter_last_success_timestamp", "Unix timestamp of last successful poll", ["inverter"], **metric_kwargs)
        self.inverter_scrape_duration = Gauge("solis_inverter_scrape_duration_seconds", "Duration of last poll in seconds", ["inverter"], **metric_kwargs)
        self.inverter_errors_total = Counter("solis_inverter_errors_total", "Total poll errors", ["inverter"], **metric_kwargs)

        self.inverter_stale = Gauge("solis_inverter_stale", "1 if data is stale, else 0", ["inverter"], **metric_kwargs)
        self.inverter_last_success_age = Gauge("solis_inverter_last_success_age_seconds", "Seconds since last success (-1 if never)", ["inverter"], **metric_kwargs)

        self.power_w = Gauge("solis_inverter_power_watts", "Current AC power output in watts", ["inverter"], **metric_kwargs)
        self.energy_today_kwh = Gauge("solis_inverter_energy_today_kwh", "Energy produced today in kWh", ["inverter"], **metric_kwargs)
        self.energy_total_kwh = Gauge("solis_inverter_energy_total_kwh", "Total energy produced in kWh", ["inverter"], **metric_kwargs)

        self.rated_power_w = Gauge("solis_inverter_rated_power_watts", "Rated power in watts (if available, else -1)", ["inverter"], **metric_kwargs)
        self.uptime_s = Gauge("solis_inverter_uptime_seconds", "Uptime seconds (if available, else -1)", ["inverter"], **metric_kwargs)
        self.alarm_present = Gauge("solis_inverter_alarm_present", "1 if alarm field is not empty, else 0", ["inverter"], **metric_kwargs)

        self.remote_status_a = Gauge("solis_remote_status_a", "Remote status A (1 enabled, 0 disabled, -1 unknown)", ["inverter"], **metric_kwargs)
        self.remote_status_b = Gauge("solis_remote_status_b", "Remote status B (1 enabled, 0 disabled, -1 unknown)", ["inverter"], **metric_kwargs)
        self.remote_status_c = Gauge("solis_remote_status_c", "Remote status C (1 enabled, 0 disabled, -1 unknown)", ["inverter"], **metric_kwargs)

        self.sta_rssi_percent = Gauge("solis_sta_rssi_percent", "STA RSSI percent (0..100)", ["inverter"], **metric_kwargs)

        self.network_info = Gauge(
            "solis_inverter_network_info",
            "Static network info as labels (value=1)",
            ["inverter", "wmode", "ap_ssid", "ap_ip", "ap_mac", "sta_ssid", "sta_ip", "sta_mac"],
            **metric_kwargs,
        )

        self.device_info = Gauge(
            "solis_inverter_device_info",
            "Static device info as labels (value=1)",
            ["inverter", "sn", "msvn", "ssvn", "pv_type", "cover_mid", "cover_ver"],
            **metric_kwargs,
        )

        for inv in self.inverters:
            self.inverter_up.labels(inverter=inv.name).set(0)
            self.inverter_last_attempt.labels(inverter=inv.name).set(0)
            self.inverter_last_success.labels(inverter=inv.name).set(0)
            self.inverter_scrape_duration.labels(inverter=inv.name).set(0)
            self.inverter_stale.labels(inverter=inv.name).set(1)
            self.inverter_last_success_age.labels(inverter=inv.name).set(-1)
            self.power_w.labels(inverter=inv.name).set(0)
            self.energy_today_kwh.labels(inverter=inv.name).set(0)
            self.energy_total_kwh.labels(inverter=inv.name).set(0)
            self.rated_power_w.labels(inverter=inv.name).set(-1)
            self.uptime_s.labels(inverter=inv.name).set(-1)
            self.alarm_present.labels(inverter=inv.name).set(0)
            self.remote_status_a.labels(inverter=inv.name).set(-1)
            self.remote_status_b.labels(inverter=inv.name).set(-1)
            self.remote_status_c.labels(inverter=inv.name).set(-1)
            self.sta_rssi_percent.labels(inverter=inv.name).set(-1)

        self.exporter_ready.set(0)

        logging.info(
            "solis-exporter port=%s inverters=%s interval=%ss timeout=%ss retries=%s parallel=%s stale=%ss default_metrics=%s",
            self.port,
            len(self.inverters),
            self.poll_interval_seconds,
            self.timeout_seconds,
            self.retries,
            self.max_parallel,
            self.stale_seconds,
            self.expose_default_metrics,
        )

    def _new_session(self, inv: InverterConfig) -> requests.Session:
        s = requests.Session()
        s.trust_env = False
        s.auth = (inv.username, inv.password)
        s.headers.update({"User-Agent": f"solis-inverter-exporter/{EXPORTER_VERSION}"})
        return s

    def _reset_session(self, inv: InverterConfig) -> None:
        lock = self._session_locks[inv.name]
        with lock:
            old = self._sessions.get(inv.name)
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._sessions[inv.name] = self._new_session(inv)

    def _request_html(self, inv: InverterConfig) -> str:
        attempts = max(1, self.retries)
        last_exc: Optional[Exception] = None
        lock = self._session_locks[inv.name]

        for i in range(attempts):
            try:
                with lock:
                    s = self._sessions[inv.name]
                    r = s.get(inv.url, timeout=self.timeout_seconds)
                r.raise_for_status()
                return r.text
            except Exception as e:
                last_exc = e
                self._reset_session(inv)
                if i < attempts - 1:
                    time.sleep(self.retry_backoff_seconds * (2 ** i))

        raise last_exc if last_exc else RuntimeError("request_failed")

    def _scrape_one(self, inv: InverterConfig) -> Tuple[str, bool, float, Optional[Dict[str, object]]]:
        start = time.time()
        self.inverter_last_attempt.labels(inverter=inv.name).set(start)

        try:
            html = self._request_html(inv)
            vars_map = parse_vars(html)

            p = to_float(vars_map.get("webdata_now_p"))
            e_today = to_float(vars_map.get("webdata_today_e"))
            e_total = to_float(vars_map.get("webdata_total_e"))

            rated = to_float(vars_map.get("webdata_rate_p"))
            rated_val = float(rated) if (rated is not None and rated > 0) else -1.0

            uptime = to_float(vars_map.get("webdata_utime"))
            uptime_val = float(uptime) if (uptime is not None and uptime > 0) else -1.0

            alarm = clean_label(vars_map.get("webdata_alarm"), default="")
            alarm_val = 1.0 if alarm.strip() else 0.0

            st_a = float(parse_status_flag(vars_map.get("status_a")))
            st_b = float(parse_status_flag(vars_map.get("status_b")))
            st_c = float(parse_status_flag(vars_map.get("status_c")))

            rssi = parse_percent(vars_map.get("cover_sta_rssi"))
            rssi_val = float(rssi) if rssi is not None else -1.0

            net_labels = {
                "wmode": clean_label(vars_map.get("cover_wmode")),
                "ap_ssid": clean_label(vars_map.get("cover_ap_ssid")),
                "ap_ip": clean_label(vars_map.get("cover_ap_ip")),
                "ap_mac": clean_label(vars_map.get("cover_ap_mac")),
                "sta_ssid": clean_label(vars_map.get("cover_sta_ssid")),
                "sta_ip": clean_label(vars_map.get("cover_sta_ip")),
                "sta_mac": clean_label(vars_map.get("cover_sta_mac")),
            }

            dev_labels = {
                "sn": clean_label(vars_map.get("webdata_sn")),
                "msvn": clean_label(vars_map.get("webdata_msvn")),
                "ssvn": clean_label(vars_map.get("webdata_ssvn")),
                "pv_type": clean_label(vars_map.get("webdata_pv_type")),
                "cover_mid": clean_label(vars_map.get("cover_mid")),
                "cover_ver": clean_label(vars_map.get("cover_ver")),
            }

            data: Dict[str, object] = {
                "power_w": p,
                "energy_today_kwh": e_today,
                "energy_total_kwh": e_total,
                "rated_power_w": rated_val,
                "uptime_s": uptime_val,
                "alarm_present": alarm_val,
                "remote_a": st_a,
                "remote_b": st_b,
                "remote_c": st_c,
                "sta_rssi_percent": rssi_val,
                "net_labels": net_labels,
                "dev_labels": dev_labels,
            }

            ok = (p is not None) or (e_today is not None) or (e_total is not None)
            dur = max(0.0, time.time() - start)
            return inv.name, ok, dur, data if ok else None
        except Exception:
            dur = max(0.0, time.time() - start)
            return inv.name, False, dur, None

    def _apply_result(self, name: str, ok: bool, duration: float, data: Optional[Dict[str, object]]) -> None:
        self.inverter_scrape_duration.labels(inverter=name).set(duration)

        if ok and data:
            self.inverter_up.labels(inverter=name).set(1)

            now = time.time()
            with self._lock:
                self._last_success[name] = now

            self.inverter_last_success.labels(inverter=name).set(now)

            p = data.get("power_w")
            if p is not None:
                self.power_w.labels(inverter=name).set(float(p))

            e_today = data.get("energy_today_kwh")
            if e_today is not None:
                self.energy_today_kwh.labels(inverter=name).set(float(e_today))

            e_total = data.get("energy_total_kwh")
            if e_total is not None:
                self.energy_total_kwh.labels(inverter=name).set(float(e_total))

            self.rated_power_w.labels(inverter=name).set(float(data.get("rated_power_w", -1.0)))
            self.uptime_s.labels(inverter=name).set(float(data.get("uptime_s", -1.0)))
            self.alarm_present.labels(inverter=name).set(float(data.get("alarm_present", 0.0)))

            self.remote_status_a.labels(inverter=name).set(float(data.get("remote_a", -1.0)))
            self.remote_status_b.labels(inverter=name).set(float(data.get("remote_b", -1.0)))
            self.remote_status_c.labels(inverter=name).set(float(data.get("remote_c", -1.0)))

            self.sta_rssi_percent.labels(inverter=name).set(float(data.get("sta_rssi_percent", -1.0)))

            if self.enable_network_info:
                net = data.get("net_labels") or {}
                self.network_info.labels(
                    inverter=name,
                    wmode=clean_label(net.get("wmode")),
                    ap_ssid=clean_label(net.get("ap_ssid")),
                    ap_ip=clean_label(net.get("ap_ip")),
                    ap_mac=clean_label(net.get("ap_mac")),
                    sta_ssid=clean_label(net.get("sta_ssid")),
                    sta_ip=clean_label(net.get("sta_ip")),
                    sta_mac=clean_label(net.get("sta_mac")),
                ).set(1)

            if self.enable_device_info:
                dev = data.get("dev_labels") or {}
                self.device_info.labels(
                    inverter=name,
                    sn=clean_label(dev.get("sn")),
                    msvn=clean_label(dev.get("msvn")),
                    ssvn=clean_label(dev.get("ssvn")),
                    pv_type=clean_label(dev.get("pv_type")),
                    cover_mid=clean_label(dev.get("cover_mid")),
                    cover_ver=clean_label(dev.get("cover_ver")),
                ).set(1)
        else:
            self.inverter_up.labels(inverter=name).set(0)
            self.inverter_errors_total.labels(inverter=name).inc()

    def _update_stale_flags(self) -> None:
        now = time.time()
        with self._lock:
            last = dict(self._last_success)

        for inv in self.inverters:
            ts = last.get(inv.name)
            if not ts:
                self.inverter_last_success_age.labels(inverter=inv.name).set(-1)
                self.inverter_stale.labels(inverter=inv.name).set(1)
                self.power_w.labels(inverter=inv.name).set(0)
                continue

            age = max(0.0, now - ts)
            self.inverter_last_success_age.labels(inverter=inv.name).set(age)

            stale = 1 if age > self.stale_seconds else 0
            self.inverter_stale.labels(inverter=inv.name).set(stale)

            if stale == 1:
                self.power_w.labels(inverter=inv.name).set(0)

    def poll_cycle(self) -> None:
        futures = []
        max_workers = max(1, min(self.max_parallel, len(self.inverters)))

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for inv in self.inverters:
                futures.append(ex.submit(self._scrape_one, inv))

            for f in as_completed(futures):
                name, ok, dur, data = f.result()
                self._apply_result(name, ok, dur, data)

        self._update_stale_flags()

        if not self._ready.is_set():
            self._ready.set()
            self.exporter_ready.set(1)

    def loop(self) -> None:
        while not self._stop.is_set():
            self.poll_cycle()
            self._stop.wait(self.poll_interval_seconds)

    def wsgi_app(self):
        metrics_app = make_wsgi_app(registry=self.registry) if self.registry is not None else make_wsgi_app()

        def app(environ, start_response):
            path = environ.get("PATH_INFO") or "/"

            if path in ("/-/healthy", "/healthz"):
                start_response("200 OK", [("Content-Type", "text/plain")])
                return [b"ok\n"]

            if path in ("/-/ready", "/readyz"):
                if self._ready.is_set():
                    start_response("200 OK", [("Content-Type", "text/plain")])
                    return [b"ready\n"]
                start_response("503 Service Unavailable", [("Content-Type", "text/plain")])
                return [b"not ready\n"]

            if path == "/" or path == "/metrics":
                return metrics_app(environ, start_response)

            start_response("404 Not Found", [("Content-Type", "text/plain")])
            return [b"not found\n"]

        return app

    def run(self) -> None:
        t = threading.Thread(target=self.loop, daemon=True)
        t.start()

        httpd = make_server("", self.port, self.wsgi_app(), server_class=ThreadingWSGIServer)

        logging.info("serving on http://0.0.0.0:%s (metrics=/metrics)", self.port)
        httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-file", dest="config_file", default=None)
    args = parser.parse_args()

    env_path = os.environ.get("SOLIS_INVERTER_EXPORTER_CONFIG")
    config_path = args.config_file or env_path or DEFAULT_CONFIG_PATH

    SolisExporter(config_path=config_path).run()


if __name__ == "__main__":
    main()
