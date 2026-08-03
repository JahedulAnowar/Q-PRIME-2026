# Bundled device feed

`qprime-devices` streams synthetic records from the paper's ten-device testbed
into the core pipeline, so a plain `docker compose up -d --build` produces a
populated dashboard with no manual ingestion. It uses only the Python standard
library, so it has no `requirements.txt`.

It is a **demonstration feed, not part of the framework**. The decision engine,
the QoC scoring and the placement algorithm it exercises are the real
implementation; only the device readings are generated. Disable it whenever you
want the stack to carry real traffic only:

```bash
docker compose stop qprime-devices     # leave the rest of the stack running
```

## Devices

| Device | Stream | Refresh | Notes |
|---|---|---|---|
| `LabDoorSensor_1` | `door` | 650 ms | contact events |
| `LabDoorSensor_2` | `door` | 650 ms | contact events |
| `LabTHPSensor` | `thp` | 650 ms | temperature / humidity / pressure |
| `SoilMoisture_1` | `soil` | 800 ms | moisture, conductivity |
| `SmokeDetector_1` | `smoke` | 500 ms | occasional alarm events |
| `HeartMonitor_1` | `heart` | 500 ms | carries a patient identity (PII) |
| `ZED2i` | `zed_vision` | 800 ms | person detections (PII) |
| `Misty Robot 1` | `misty_vision` | 810 ms | face recognition (PII) |
| `Tello Drone 1` | `tello_vision` | 1000 ms | `privacy_filter: strict`, pinned to edge |
| `RGBCamera_1` | `camera_vision` | 900 ms | person detections (PII) |

Payloads match `services/core/schema/*-schema.json`, so the QoC completeness
factor is scored against the same field sets the paper used. A configurable
fraction of records is emitted degraded (a dropped or out-of-range field) to
exercise completeness and correctness, and every stream emits periodic
`heartbeat` events to exercise significance.

## Configuration

| Variable | Default | Effect |
|---|---|---|
| `QPRIME_CORE_URL` | `http://qprime-analysis:5005` | Core ingestion endpoint |
| `QPRIME_DEVICES_TRANSPORT` | `both` | `both`, `direct`, or `edgex` |
| `QPRIME_DEVICES_RATE_PER_MIN` | `240` | Steady-state records per minute |
| `QPRIME_DEVICES_INITIAL_BURST` | `400` | Records sent at full speed on startup |
| `QPRIME_DEVICES_DEGRADED_PCT` | `0.08` | Fraction of records emitted degraded |
| `QPRIME_DEVICES_MAX_RECORDS` | `0` | Stop after N records (`0` runs forever) |
| `QPRIME_DEVICES_SEED` | *(unset)* | Fix the RNG seed for repeatable runs |

## Transports

`direct` posts canonical records to `POST /api/ingest`.

`edgex` registers one REST device profile per stream and one EdgeX device per
simulated device in core-metadata, then pushes each reading to `device-rest`, so
records travel the full device → EdgeX core-data → `app-service-configurable`
HTTP export → `POST /api/ingest/edgex` path.

The canonical Q-PRIME metadata (`contextAttribute`, `refreshRate`,
`privacy_filter`, `device_id`, `gateway_id`) travels as EdgeX **device tags**,
which core-data copies onto every event and `normalize_edgex` reads back out.
Records arriving through EdgeX are therefore scored identically to direct
ones — including the drone's `privacy_filter: strict` edge pin.

`both` (the default) alternates the two, so one `docker compose up` exercises
the entire topology. Filter by entry point in the Decisions tab, or via the API:

```bash
curl 'http://localhost:5005/api/results/decisions?source=edgex&limit=5'
curl 'http://localhost:5005/api/results/decisions?source=direct&limit=5'
```

If EdgeX is unreachable at startup, or stops accepting readings mid-run, the
feed logs a warning and falls back to `direct` so the dashboards keep
populating.
