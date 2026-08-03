"""Synthetic device catalogue for the bundled Q-PRIME demonstration feed.

The ten devices below mirror the testbed described in the paper: two vision
robots, a drone, an RGB camera, a stereo camera, two door contacts, a
temperature/humidity/pressure node, a soil probe, a smoke detector and a
wearable heart monitor.

Each generator emits records in the canonical shape accepted by
``POST /api/ingest`` and matching ``services/core/schema/*-schema.json``, so the
QoC completeness factor is scored against the same field sets the paper used.
Payloads deliberately span the full behaviour space of the decision engine:

* vision streams carry identities, so the privacy analytics populate;
* the drone sets ``privacy_filter`` strict, exercising the hard Edge override;
* every stream emits occasional ``heartbeat`` events, exercising significance;
* a small fraction of records is emitted degraded (missing or out-of-range
  fields), exercising completeness and correctness.
"""

import random
import time
import uuid

GATEWAYS = ("edge-node-1", "edge-node-2", "edge-node-3", "edge-node-4")

FIRST_NAMES = (
    "Arthur", "Alice", "Priya", "Marcus", "Lena", "Tomas", "Nadia", "Rohan",
    "Sofia", "Ewan", "Mei", "Jonas",
)
LAST_NAMES = (
    "Bray", "Okafor", "Nguyen", "Halloran", "Petrov", "Silva", "Iqbal",
    "Fischer", "Costa", "Dubois",
)


def _person():
    return f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"


def _ssn():
    return f"{random.randint(100, 899):03d}-{random.randint(10, 99):02d}-{random.randint(1000, 9999):04d}"


def _drift(centre, spread, low=None, high=None):
    value = random.gauss(centre, spread)
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return round(value, 2)


# --------------------------------------------------------------------- streams
def door_value(heartbeat):
    if heartbeat:
        event, state, contact = "heartbeat", "closed", True
    else:
        opened = random.random() < 0.5
        event = "opened" if opened else "closed"
        state = "open" if opened else "closed"
        contact = not opened
    return {
        "battery": _drift(88, 6, 0, 100),
        "contact": contact,
        "device_temperature": _drift(22, 2),
        "linkquality": random.randint(40, 160),
        "power_outage_count": 0,
        "state": state,
        "voltage": _drift(3000, 40),
        "event": event,
    }


def thp_value(heartbeat):
    return {
        "battery": _drift(91, 5, 0, 100),
        "device_temperature": _drift(23, 2),
        "humidity": _drift(58, 9, 0, 100),
        "linkquality": random.randint(40, 160),
        "power_outage_count": 0,
        "pressure": _drift(1008, 6),
        "temperature": _drift(24, 3),
        "voltage": _drift(3000, 40),
        "event": "heartbeat" if heartbeat else "reading",
    }


def soil_value(heartbeat):
    return {
        "event": "heartbeat" if heartbeat else "moisture_reading",
        "moisture": _drift(41, 11, 0, 100),
        "soil_temperature": _drift(19, 3),
        "conductivity_us_cm": _drift(820, 90, 0),
        "battery": _drift(84, 7, 0, 100),
    }


def smoke_value(heartbeat):
    alarm = (not heartbeat) and random.random() < 0.04
    return {
        "event": "heartbeat" if heartbeat else ("smoke_alarm" if alarm else "clear"),
        "smoke_detected": alarm,
        "obscuration_pct_ft": _drift(6.5 if alarm else 0.4, 0.8, 0),
        "battery": _drift(93, 4, 0, 100),
        "test_mode": False,
    }


def heart_value(heartbeat):
    """Wearable stream: ``patient`` is a direct identifier, so PII is detected."""
    return {
        "event": "heartbeat" if heartbeat else "vitals_reading",
        "patient": _person(),
        "person": _person(),
        "bpm": random.randint(52, 128),
        "spo2": _drift(97, 1.2, 80, 100),
        "hrv_ms": _drift(48, 12, 0),
        "battery": _drift(76, 12, 0, 100),
    }


def zed_value(heartbeat):
    count = 0 if heartbeat else random.randint(0, 3)
    detections = [
        {
            "id": index,
            "label": "person",
            "position_m": {
                "x": _drift(0, 2.5),
                "y": _drift(0, 1.5),
                "z": _drift(4, 1.8, 0),
            },
            "distance_m": _drift(4.2, 1.6, 0),
            "confidence": _drift(0.86, 0.09, 0, 1),
            "tracking_state": random.choice(("OK", "SEARCHING")),
        }
        for index in range(count)
    ]
    return {
        "event": "heartbeat" if heartbeat else ("person_detected" if count else "scene_clear"),
        "count": count,
        "detections": detections,
    }


def misty_value(heartbeat):
    known = random.random() < 0.65
    return {
        "distance": random.randint(30, 240),
        "event": "heartbeat"
        if heartbeat
        else ("familiar_face_detected" if known else "unknown_face_detected"),
        "person": _person() if known else "unknown",
        "pitch": random.randint(-20, 20),
        "yaw": random.randint(-45, 45),
    }


def tello_value(heartbeat):
    humans = 0 if heartbeat else random.randint(0, 2)
    detections = [
        {
            "type": "person",
            "name": _person(),
            "age": random.randint(19, 71),
            "gender": random.choice(("Male", "Female")),
            "ssn": _ssn(),
            "confidence": _drift(0.68, 0.14, 0, 1),
            "x": random.randint(0, 1920),
            "y": random.randint(0, 1080),
        }
        for _ in range(humans)
    ]
    return {
        "box_id": uuid.uuid4().hex,
        "id": str(uuid.uuid4()),
        "roi_id": f"roiID_{random.randint(0, 3)}",
        "type": 1,
        "bboxs": [
            {"x": random.randint(0, 5000), "y": random.randint(0, 5000)},
            {"x": random.randint(5000, 9999), "y": random.randint(5000, 9999)},
        ],
        "human_count": humans,
        "detections": detections,
        "is_pushed": True,
        "event": "heartbeat" if heartbeat else "aerial_survey",
    }


def camera_value(heartbeat):
    count = 0 if heartbeat else random.randint(0, 4)
    return {
        "event": "heartbeat" if heartbeat else ("motion_detected" if count else "idle"),
        "count": count,
        "detections": [
            {
                "label": "person",
                "name": _person(),
                "confidence": _drift(0.79, 0.11, 0, 1),
                "bbox": [random.randint(0, 1900) for _ in range(4)],
            }
            for _ in range(count)
        ],
        "frame_id": random.randint(1, 10**6),
        "resolution": "1920x1080",
    }


# --------------------------------------------------------------------- catalogue
# ``latency_spread_ms`` shapes the timeliness factor: values are drawn around it
# and compared against the stream's threshold in config/qoc_thresholds.json.
DEVICES = (
    {
        "device_name": "LabDoorSensor_1",
        "stream": "door",
        "builder": door_value,
        "refresh_rate": 650,
        "latency_spread_ms": 260,
        "heartbeat_pct": 0.25,
    },
    {
        "device_name": "LabDoorSensor_2",
        "stream": "door",
        "builder": door_value,
        "refresh_rate": 650,
        "latency_spread_ms": 300,
        "heartbeat_pct": 0.25,
    },
    {
        "device_name": "LabTHPSensor",
        "stream": "thp",
        "builder": thp_value,
        "refresh_rate": 650,
        "latency_spread_ms": 280,
        "heartbeat_pct": 0.15,
    },
    {
        "device_name": "SoilMoisture_1",
        "stream": "soil",
        "builder": soil_value,
        "refresh_rate": 800,
        "latency_spread_ms": 340,
        "heartbeat_pct": 0.15,
    },
    {
        "device_name": "SmokeDetector_1",
        "stream": "smoke",
        "builder": smoke_value,
        "refresh_rate": 500,
        "latency_spread_ms": 190,
        "heartbeat_pct": 0.30,
    },
    {
        "device_name": "HeartMonitor_1",
        "stream": "heart",
        "builder": heart_value,
        "refresh_rate": 500,
        "latency_spread_ms": 180,
        "heartbeat_pct": 0.10,
    },
    {
        "device_name": "ZED2i",
        "stream": "zed_vision",
        "builder": zed_value,
        "refresh_rate": 800,
        "latency_spread_ms": 330,
        "heartbeat_pct": 0.10,
    },
    {
        "device_name": "Misty Robot 1",
        "stream": "misty_vision",
        "builder": misty_value,
        "refresh_rate": 810,
        "latency_spread_ms": 340,
        "heartbeat_pct": 0.10,
    },
    {
        "device_name": "Tello Drone 1",
        "stream": "tello_vision",
        "builder": tello_value,
        "refresh_rate": 1000,
        "latency_spread_ms": 420,
        "heartbeat_pct": 0.10,
        # The paper pins this stream to the edge regardless of its QoC scores.
        "privacy_filter": "strict",
    },
    {
        "device_name": "RGBCamera_1",
        "stream": "camera_vision",
        "builder": camera_value,
        "refresh_rate": 900,
        "latency_spread_ms": 360,
        "heartbeat_pct": 0.10,
    },
)


def build_catalogue():
    """Assign each device a stable identity for the lifetime of the process."""
    catalogue = []
    for spec in DEVICES:
        device = dict(spec)
        device["device_id"] = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, f"qprime.{spec['device_name']}")
        )
        device["gateway_id"] = random.choice(GATEWAYS)
        device["ip_address"] = f"192.168.11.{random.randint(20, 240)}"
        catalogue.append(device)
    return catalogue


def _degrade(value):
    """Drop a field or push one out of range, to vary completeness/correctness."""
    keys = [key for key in value if key not in ("event",)]
    if not keys:
        return value
    victim = random.choice(keys)
    if random.random() < 0.5:
        value.pop(victim, None)
    elif isinstance(value.get(victim), (int, float)) and not isinstance(value[victim], bool):
        value[victim] = -abs(value[victim]) * 10
    else:
        value.pop(victim, None)
    return value


def make_record(device, degraded_pct=0.08):
    """Return one canonical Q-PRIME record for ``device``."""
    heartbeat = random.random() < device.get("heartbeat_pct", 0.15)
    value = device["builder"](heartbeat)
    if random.random() < degraded_pct:
        value = _degrade(value)

    # Backdate the reading so the timeliness factor sees a realistic delay.
    latency_ms = max(0, random.gauss(device["latency_spread_ms"], device["latency_spread_ms"] / 3))
    record = {
        "entity": device["gateway_id"],
        "contextAttribute": device["stream"],
        "contextValue": value,
        "refreshRate": device["refresh_rate"],
        "timestamp": int(time.time() * 1000 - latency_ms),
        "resource": {
            "device_id": device["device_id"],
            "device_name": device["device_name"],
            "sensor_id": device["stream"],
            "gateway_id": device["gateway_id"],
            "ip_address": device["ip_address"],
        },
        "sla": None,
        "privacy_filter": device.get("privacy_filter", False),
    }
    # The core derives a content hash for idempotency; a per-record nonce keeps
    # bursts within the same second from collapsing into duplicates.
    record["record_id"] = f"{device['device_id']}:{uuid.uuid4().hex}"
    return record
