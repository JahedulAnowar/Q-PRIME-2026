"""Stateless five-factor Quality-of-Context evaluation."""

import json
import os
import threading
import time
from glob import glob
from typing import Dict, Optional

from .config import RuntimeConfig

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA_DIR = os.environ.get("QPRIME_SCHEMA_DIR", os.path.join(BASE_DIR, "schema"))

_schema_lock = threading.RLock()
_expected_keys: Optional[Dict[str, list]] = None


def _collect(obj, prefix=""):
    keys = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            new_prefix = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                keys.extend(_collect(value, new_prefix))
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                keys.extend(_collect(value[0], new_prefix))
            else:
                keys.append(new_prefix)
    return keys


def expected_keys() -> Dict[str, list]:
    """Load and cache immutable expected field paths from ``schema/``."""
    global _expected_keys
    with _schema_lock:
        if _expected_keys is None:
            result: Dict[str, list] = {}
            for path in glob(os.path.join(SCHEMA_DIR, "*-schema.json")):
                try:
                    with open(path, "r") as schema_file:
                        schema = json.load(schema_file)
                except Exception:
                    continue
                name = os.path.basename(path).replace("-schema.json", "")
                result[name.lower()] = _collect(schema)
            _expected_keys = result
        return _expected_keys


def reset_baselines() -> None:
    """Compatibility no-op: record-derived baselines are not retained."""


def _has_path(obj, path):
    current = obj
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _latency_threshold(stream_key: str, config: dict) -> int:
    thresholds = {
        str(key).lower(): int(value)
        for key, value in (config.get("latency_thresholds") or {}).items()
    }
    if stream_key in thresholds:
        return thresholds[stream_key]
    for key in thresholds:
        if key in stream_key or stream_key in key:
            return thresholds[key]
    return int(config.get("default_latency_threshold_ms", 30))


def _find_expected(stream_key: str):
    configured = expected_keys()
    if stream_key in configured:
        return configured[stream_key]
    for key in configured:
        if key in stream_key or stream_key in key:
            return configured[key]
    return ["timestamp"]


def _timestamp_ms(value) -> Optional[int]:
    if not isinstance(value, (int, float)):
        return None
    integer = int(value)
    return integer if integer > 1_000_000_000_000 else integer * 1000


def compute_slas(data: dict, config: dict) -> dict:
    """Evaluate all five QoC factors for one caller-supplied record."""
    pass_threshold = float(config.get("pass_threshold", 0.6))
    stream_key = (data.get("contextAttribute") or "").lower()

    latency_ms = None
    timeliness_score = 0.0
    timestamp_ms = _timestamp_ms(data.get("timestamp"))
    if timestamp_ms is not None:
        latency_ms = max(0, int(time.time() * 1000) - timestamp_ms)
        maximum_ms = _latency_threshold(stream_key, config)
        timeliness_score = max(0.0, 1.0 - latency_ms / max(maximum_ms, 1))

    expected = _find_expected(stream_key)
    present = sum(1 for key in expected if _has_path(data, key))
    completeness_score = present / len(expected) if expected else 0.0

    context_value = data.get("contextValue", {}) or {}
    correctness_checks = []
    if "distance" in context_value:
        try:
            distance = float(context_value.get("distance"))
            correctness_checks.append(1.0 if 0 <= distance < 10000 else 0.0)
        except Exception:
            correctness_checks.append(0.0)
    if "event" in context_value:
        correctness_checks.append(
            1.0 if isinstance(context_value.get("event"), str) else 0.0
        )
    correctness_checks.append(1.0 if _has_path(data, "resource.device_id") else 0.0)
    correctness_score = sum(correctness_checks) / len(correctness_checks)

    refresh_rate = data.get("refreshRate")
    if isinstance(refresh_rate, (int, float)) and refresh_rate > 0:
        resolution_score = 1.0 - min(
            max((float(refresh_rate) - 1) / 10000.0, 0.0), 1.0
        )
    else:
        resolution_score = 0.5

    event = (context_value.get("event") or "").lower()
    if event and event not in {"heartbeat", "status", "ok"}:
        significance_score = 1.0
    elif event:
        significance_score = 0.2
    else:
        significance_score = 0.5

    def passed(score):
        return bool(score >= pass_threshold)

    return {
        "timeliness": {
            "score": round(timeliness_score, 3),
            "latency_ms": int(latency_ms) if latency_ms is not None else None,
            "passed": passed(timeliness_score),
        },
        "completeness": {
            "score": round(completeness_score, 3),
            "present": present,
            "expected": len(expected),
            "passed": passed(completeness_score),
        },
        "correctness": {
            "score": round(correctness_score, 3),
            "passed": passed(correctness_score),
        },
        "resolution": {
            "score": round(resolution_score, 3),
            "passed": passed(resolution_score),
        },
        "significance": {
            "score": round(significance_score, 3),
            "passed": passed(significance_score),
        },
    }


def evaluate(data: dict, runtime: RuntimeConfig) -> dict:
    """Evaluate a record without retaining record-derived state."""
    return compute_slas(data, runtime.snapshot())
