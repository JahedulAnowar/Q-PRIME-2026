"""Stateless HTTP API for the Q-PRIME paper algorithms.

The service evaluates a caller-supplied context record in memory and returns
its Quality-of-Context scores, privacy findings, AHP-derived weights, and
placement recommendation. It never ingests, routes, stores, or queries sensor
data; callers retain ownership of the record and all persistence decisions.
"""

import copy
import os
import time

from dotenv import load_dotenv
from flask import Flask, jsonify, request

from qprime import __version__
from qprime import ahp as ahp_mod
from qprime import decision as decision_mod
from qprime import sla as sla_mod
from qprime.config import RuntimeConfig, runtime_config

load_dotenv()

app = Flask(__name__)
START_MS = int(time.time() * 1000)


@app.after_request
def cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, OPTIONS"
    return response


@app.route("/")
def index():
    return jsonify(
        {
            "service": "qprime-analysis",
            "version": __version__,
            "mode": "stateless",
            "uptime_ms": int(time.time() * 1000) - START_MS,
        }
    )


@app.route("/api/health")
def health():
    return jsonify(
        {
            "status": "ok",
            "service": "qprime-analysis",
            "version": __version__,
            "mode": "stateless",
        }
    )


@app.route("/api/config", methods=["GET", "PUT", "OPTIONS"])
def config_endpoint():
    if request.method == "OPTIONS":
        return ("", 204)
    if request.method == "GET":
        return jsonify(runtime_config.snapshot())
    try:
        patch = request.get_json(force=True) or {}
        return jsonify(runtime_config.update(patch))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/config/ahp", methods=["POST", "OPTIONS"])
def config_ahp():
    """Evaluate a 3x3 pairwise matrix and optionally apply it to defaults."""
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        body = request.get_json(force=True) or {}
        if "matrix" in body:
            matrix = body["matrix"]
        else:
            judgements = body.get("judgements") or {}
            matrix = ahp_mod.matrix_from_judgements(
                float(judgements.get("temporal_vs_spatial", 1.0)),
                float(judgements.get("temporal_vs_privacy", 1.0)),
                float(judgements.get("spatial_vs_privacy", 1.0)),
            )
        ahp_mod.validate_matrix(matrix)
        weights, lambda_max, consistency_index, consistency_ratio = (
            ahp_mod.ahp_weights_and_consistency(matrix)
        )
        result = {
            "matrix": matrix,
            "weights": {
                "temporal": round(weights[0], 4),
                "spatial": round(weights[1], 4),
                "privacy": round(weights[2], 4),
            },
            "lambda_max": round(lambda_max, 4),
            "consistency_index": round(consistency_index, 4),
            "consistency_ratio": round(consistency_ratio, 4),
            "consistent": consistency_ratio < 0.10,
            "applied": False,
        }
        if body.get("apply"):
            runtime_config.update({"ahp_matrix": matrix, "weight_mode": "global_ahp"})
            result["applied"] = True
        return jsonify(result)
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


def _analysis_runtime(config_patch):
    if config_patch is None:
        return runtime_config
    if not isinstance(config_patch, dict):
        raise ValueError("config must be a JSON object")
    runtime = RuntimeConfig()
    runtime.update(config_patch)
    return runtime


@app.route("/api/analyze", methods=["POST", "OPTIONS"])
def analyze():
    """Return an in-memory analysis of one record, without side effects.

    Accepted body:
        {"record": {...}, "config": {...optional runtime overrides...}}

    A raw record object is also accepted when no per-request configuration is
    needed.
    """
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        body = request.get_json(force=True, silent=False)
        if not isinstance(body, dict):
            return jsonify({"error": "request body must be a JSON object"}), 400

        wrapped = "record" in body
        record = body.get("record") if wrapped else body
        config_patch = body.get("config") if wrapped else None
        if not isinstance(record, dict):
            return jsonify({"error": "record must be a JSON object"}), 400
        if not str(record.get("contextAttribute") or "").strip():
            return jsonify({"error": "record is missing contextAttribute"}), 400

        runtime = _analysis_runtime(config_patch)
        evaluated = copy.deepcopy(record)
        evaluated["sla"] = sla_mod.evaluate(evaluated, runtime)
        recommendation = decision_mod.decide(evaluated, runtime)

        return jsonify(
            {
                "analysis": recommendation,
                "qoc": evaluated["sla"],
                "config": runtime.snapshot(),
            }
        )
    except (TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400


if __name__ == "__main__":
    port = int(os.getenv("QPRIME_ANALYSIS_PORT", "5005"))
    app.run(host="0.0.0.0", port=port, threaded=True)
