"""Bundled device feed for the Q-PRIME demonstration stack.

Streams synthetic records from the paper's ten-device testbed into the core
pipeline so that a plain ``docker compose up`` produces a populated dashboard
without any manual ingestion.

Transports
----------
``both``    Alternate between the two below (default), so a single
            ``docker compose up`` exercises the entire topology.
``direct``  POST canonical records to ``/api/ingest``.
``edgex``   Provision a REST device per simulated device in EdgeX core-metadata
            and push readings through ``device-rest``, exercising the full
            device -> EdgeX core-data -> http-export -> core path.

If EdgeX is unreachable at startup, or stops accepting readings mid-run, the
feed falls back to ``direct`` so the dashboards keep populating.

Everything is controlled by environment variables; see docker-compose.yml.
"""

import json
import logging
import os
import random
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from devices import DEVICES, build_catalogue, make_record

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  qprime-devices  %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("qprime-devices")


def _env(name, default):
    value = os.getenv(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_float(name, default):
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name, default):
    try:
        return int(float(_env(name, str(default))))
    except ValueError:
        return default


CORE_URL = _env("QPRIME_CORE_URL", "http://qprime-analysis:5005").rstrip("/")
EDGEX_METADATA_URL = _env("EDGEX_METADATA_URL", "http://edgex-core-metadata:59881").rstrip("/")
EDGEX_DEVICE_REST_URL = _env("EDGEX_DEVICE_REST_URL", "http://edgex-device-rest:59986").rstrip("/")
TRANSPORT = _env("QPRIME_DEVICES_TRANSPORT", "both").lower()
RECORDS_PER_MINUTE = _env_float("QPRIME_DEVICES_RATE_PER_MIN", 240)
INITIAL_BURST = _env_int("QPRIME_DEVICES_INITIAL_BURST", 400)
DEGRADED_PCT = _env_float("QPRIME_DEVICES_DEGRADED_PCT", 0.08)
MAX_RECORDS = _env_int("QPRIME_DEVICES_MAX_RECORDS", 0)  # 0 = run forever
SEED = _env("QPRIME_DEVICES_SEED", "")

EDGEX_PROFILE_PREFIX = "qprime-demo"
STREAMS = sorted({device["stream"] for device in DEVICES})

_running = True


def _stop(signum, _frame):
    global _running
    _running = False
    log.info("received signal %s, shutting down", signum)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


# ------------------------------------------------------------------ transport
def _post(url, payload, timeout=10):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def _get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.status, response.read()


def wait_for_core(deadline_s=300):
    """Block until the core answers, so the first record is never dropped."""
    started = time.time()
    while _running and time.time() - started < deadline_s:
        try:
            status, _ = _get(f"{CORE_URL}/api/health", timeout=5)
            if status == 200:
                log.info("core is ready at %s", CORE_URL)
                return True
        except (urllib.error.URLError, OSError, ValueError):
            pass
        time.sleep(2)
    log.error("core did not become ready at %s within %ss", CORE_URL, deadline_s)
    return False


def send_direct(record):
    status, _ = _post(f"{CORE_URL}/api/ingest", record)
    return status == 200


# --------------------------------------------------------------------- EdgeX
def _edgex_profile(stream):
    """One REST profile per stream, exposing the stream as a JSON resource."""
    return {
        "apiVersion": "v3",
        "profile": {
            "name": f"{EDGEX_PROFILE_PREFIX}-{stream}",
            "manufacturer": "Q-PRIME",
            "model": "demo-feed",
            "description": f"Synthetic Q-PRIME {stream} stream delivered over device-rest",
            "labels": ["qprime", "demo", stream],
            "deviceResources": [
                {
                    "name": stream,
                    "description": f"{stream} context record",
                    "properties": {"valueType": "Object", "readWrite": "W"},
                }
            ],
        },
    }


def _edgex_device(device):
    """Register one EdgeX device per simulated device.

    The canonical Q-PRIME metadata travels as EdgeX device tags. ``core-data``
    copies device tags onto every event, and ``normalize_edgex`` reads
    ``contextAttribute``, ``refreshRate``, ``privacy_filter``, ``device_id``,
    ``gateway_id`` and ``entity`` back out of them, so records arriving through
    EdgeX are scored identically to those posted directly.
    """
    return {
        "apiVersion": "v3",
        "device": {
            # Matching the simulated name keeps `resource.device_name` intact:
            # normalize_edgex prefers the event's deviceName over the tag.
            "name": device["device_name"],
            "description": f"Synthetic Q-PRIME {device['stream']} device",
            "adminState": "UNLOCKED",
            "operatingState": "UP",
            "labels": ["qprime", "demo", device["stream"]],
            "serviceName": "device-rest",
            "profileName": f"{EDGEX_PROFILE_PREFIX}-{device['stream']}",
            "protocols": {"other": {}},
            "tags": {
                "contextAttribute": device["stream"],
                "refreshRate": device["refresh_rate"],
                "privacy_filter": device.get("privacy_filter", False),
                "device_id": device["device_id"],
                "device_name": device["device_name"],
                "gateway_id": device["gateway_id"],
                "entity": device["gateway_id"],
            },
        },
    }


def _edgex_create(path, payload):
    """POST an EdgeX create request; an existing object is treated as success."""
    try:
        status, _body = _post(f"{EDGEX_METADATA_URL}{path}", [payload], timeout=10)
        return 200 <= status < 300
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        if exc.code == 409 or "duplicate" in detail.lower():
            return True
        log.warning("EdgeX %s failed: HTTP %s %s", path, exc.code, detail[:200])
        return False
    except (urllib.error.URLError, OSError) as exc:
        log.warning("EdgeX %s unreachable: %s", path, exc)
        return False


def provision_edgex(catalogue, deadline_s=180):
    """Register a profile per stream and a device per simulated device."""
    started = time.time()
    while _running and time.time() - started < deadline_s:
        try:
            _get(f"{EDGEX_METADATA_URL}/api/v3/ping", timeout=5)
        except (urllib.error.URLError, OSError):
            time.sleep(3)
            continue
        if not all(_edgex_create("/api/v3/deviceprofile", _edgex_profile(s)) for s in STREAMS):
            time.sleep(3)
            continue
        if not all(_edgex_create("/api/v3/device", _edgex_device(d)) for d in catalogue):
            time.sleep(3)
            continue
        log.info("provisioned %d EdgeX devices across %d profiles", len(catalogue), len(STREAMS))
        # device-rest needs a moment to pick up the new devices from metadata.
        time.sleep(5)
        return True
    return False


def send_edgex(record):
    """Push one record through device-rest as a JSON object reading."""
    device = urllib.parse.quote(record["resource"]["device_name"], safe="")
    resource = urllib.parse.quote(record["contextAttribute"], safe="")
    url = f"{EDGEX_DEVICE_REST_URL}/api/v3/resource/{device}/{resource}"
    status, _ = _post(url, record["contextValue"])
    return 200 <= status < 300


# ---------------------------------------------------------------------- main
def main():
    if SEED:
        random.seed(SEED)
        log.info("deterministic seed: %s", SEED)

    catalogue = build_catalogue()
    log.info(
        "%d devices across %d streams; transport=%s rate=%s rec/min",
        len(catalogue),
        len(STREAMS),
        TRANSPORT,
        RECORDS_PER_MINUTE,
    )

    if not wait_for_core():
        return 1

    transport = TRANSPORT
    if transport in ("edgex", "both") and not provision_edgex(catalogue):
        log.warning("EdgeX provisioning failed; falling back to direct ingestion")
        transport = "direct"

    interval = 60.0 / max(RECORDS_PER_MINUTE, 1e-6)
    sent = failed = 0
    edgex_failures = 0
    next_report = time.time() + 30
    use_edgex = transport in ("edgex", "both")

    log.info("initial burst of %d records, then %.0f records/minute", INITIAL_BURST, RECORDS_PER_MINUTE)

    while _running:
        device = random.choice(catalogue)
        record = make_record(device, DEGRADED_PCT)
        attempted_edgex = use_edgex
        try:
            ok = send_edgex(record) if use_edgex else send_direct(record)
            sent += int(ok)
            failed += int(not ok)
            if ok and attempted_edgex:
                edgex_failures = 0
        except urllib.error.HTTPError as exc:
            failed += 1
            edgex_failures += int(attempted_edgex)
            if failed <= 5 or failed % 100 == 0:
                log.warning(
                    "ingest rejected (%s): %s",
                    exc.code,
                    exc.read().decode("utf-8", "replace")[:200],
                )
        except (urllib.error.URLError, OSError) as exc:
            failed += 1
            edgex_failures += int(attempted_edgex)
            if failed <= 5 or failed % 100 == 0:
                log.warning("ingest unreachable: %s", exc)
            time.sleep(1)

        # If EdgeX stops accepting readings mid-run, keep the dashboard alive by
        # switching the whole feed to direct ingestion rather than losing records.
        if edgex_failures >= 20 and transport != "direct":
            log.warning("EdgeX transport failed %d times in a row; switching to direct", edgex_failures)
            transport = "direct"
            use_edgex = False
            edgex_failures = 0
        elif transport == "both":
            use_edgex = not use_edgex

        if MAX_RECORDS and sent >= MAX_RECORDS:
            log.info("reached QPRIME_DEVICES_MAX_RECORDS=%d, stopping", MAX_RECORDS)
            break

        if time.time() >= next_report:
            log.info("ingested %d records (%d failed)", sent, failed)
            next_report = time.time() + 30

        # The opening burst fills the dashboards quickly; then settle to the
        # configured steady-state rate.
        if sent + failed >= INITIAL_BURST:
            time.sleep(interval)

    log.info("stopped after %d records (%d failed)", sent, failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
