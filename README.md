# Q-PRIME

**A Quality- and Privacy-Aware Edge–Cloud Continuum Framework for Internet of Things Applications**

[![Docker](https://img.shields.io/badge/docker-one--command%20deploy-2496ED?logo=docker&logoColor=white)](#-quick-start)
[![EdgeX Foundry](https://img.shields.io/badge/EdgeX%20Foundry-3.1%20Napa-blueviolet)](https://www.edgexfoundry.org/)
[![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)](#)
[![Tests](https://img.shields.io/badge/tests-96%20passing-2fbf71)](#-reproducing-the-papers-results)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Q-PRIME decides — per record, in real time — whether IoT data should be stored at the **edge** or in the **cloud**, by scoring each record on five Quality-of-Context (QoC) factors (*timeliness, completeness, correctness, resolution, significance*) and combining them with **privacy awareness** through criteria weights that can be set directly or derived from an **AHP pairwise comparison matrix**.

Placement is only half the story: the data must stay **usable** afterwards. Q-PRIME therefore exposes the whole edge–cloud continuum as **one queryable surface**, and ships the AI/NLP application service from the paper — ask *“how many door events today?”* in plain English and the answer spans both tiers.

This repository is the research software release accompanying the paper:

> K. S. Jagarlamudi *et al.*, “A Quality- and Privacy-Aware Edge–Cloud Continuum Framework for Internet of Things Applications”, *IEEE Access* (under review), 2026.

This repository does not directly connect devices, ingest records, operate databases, route records, or persist sensor data. Those responsibilities belong to external integration software and data infrastructure. Users can either connect to their real devices or through the simulator.

## Architecture

```text
caller-owned record
    -> stateless analysis API
    -> QoC scores + privacy findings + AHP weights + tier recommendation

user question
    -> NLP service generates read-only SQL
    -> external QUERY_API_URL reads user-owned data
    -> NLP summarises rows
    -> Next.js query application renders answers and charts
```

The analysis and query flows are separate. The analysis API never sends its input to the query endpoint.

## Components

| Component | Location | Default URL | Responsibility |
|---|---|---|---|
| Stateless analysis API | `services/core` | <http://localhost:5005> | QoC, privacy, AHP, and placement recommendation |
| NLP API | `services/nlp` | <http://localhost:5500> | Natural language to SQL and result summarisation |
| Query application | `services/nlp-web` | <http://localhost:3000> | Chat, read-only queries, cards, and charts |
| Optional Ollama | Compose profile `llm` | <http://localhost:11434> | Optional model-assisted SQL or summaries |

## Stateless paper analysis

Every caller-supplied record is evaluated in memory:

- **timeliness:** `1 − latency/threshold`;
- **completeness:** expected schema fields present;
- **correctness:** type and range checks;
- **resolution:** score derived from the refresh rate;
- **significance:** event-content heuristic; and
- **privacy:** PII detection plus a stream-specific privacy weight.

The placement scores are:

```text
QoC_temporal = mean(timeliness, resolution)
QoC_content  = mean(completeness, correctness, significance)

S_edge  = w_temporal * QoC_temporal + w_privacy * P
S_cloud = w_content  * QoC_content
```

The larger score determines the recommendation; equal scores recommend `Both`. A strict privacy flag can override the calculation and recommend `Edge`.

Criteria weights can be per-stream, global direct values, or derived from a 3×3 AHP pairwise-comparison matrix. AHP responses include λmax, consistency index, and consistency ratio.

### Analysis API

```text
GET  /api/health
GET  /api/config
PUT  /api/config
POST /api/config/ahp
POST /api/analyze
```

Analyze a record using the active configuration:

```bash
curl -X POST http://localhost:5005/api/analyze \
  -H 'Content-Type: application/json' \
  -d '{
    "contextAttribute": "door",
    "contextValue": {"event": "opened"},
    "resource": {"device_id": "door-1", "device_name": "Door 1"},
    "refreshRate": 1000,
    "timestamp": 1785312000,
    "privacy_filter": false
  }'
```

For request-specific settings without modifying the active defaults, send:

```json
{
  "record": {"contextAttribute": "door", "contextValue": {}, "resource": {}},
  "config": {
    "weight_mode": "global_direct",
    "global_criteria_weights": {"temporal": 0.5, "spatial": 0.3, "privacy": 0.2}
  }
}
```

The response contains `qoc`, the complete `analysis` explanation, and the effective `config`. No record is retained after the response.

## External query contract

Set `QUERY_API_URL` to an externally operated HTTP endpoint. The NLP and web services call it with:

```http
GET <QUERY_API_URL>?query=<url-encoded SQL>&isCloud=<continuum|false|true>&query_timestamp=<milliseconds>
```

The endpoint must return JSON shaped like:

```json
{
  "results": [{"device_name": "Door 1", "event": "opened"}],
  "edge_count": 1,
  "cloud_count": 0,
  "scope": "continuum"
}
```

`isCloud=false` requests the edge scope, `isCloud=true` requests the cloud scope, and `isCloud=continuum` requests the combined view. The external implementation owns authentication, SQL execution, source selection, and all data access.

When `QUERY_API_URL` is absent, the UIs return a clear setup-required response and do not attempt a local fallback.

## Quick start

Requirements: Docker 24+ with Compose v2.

```bash
cp .env.example .env
# Set QUERY_API_URL in .env when an external source is available.
docker compose up -d --build
```

Open:

- query application: <http://localhost:3000>
- analysis API: <http://localhost:5005/api/health>
- NLP API: <http://localhost:5500/api/health>

The analysis API and rule-based NLP logic work without an LLM. Data queries require `QUERY_API_URL`.

## Optional local language model

```bash
docker compose --profile llm up -d ollama
docker compose --profile llm exec ollama ollama pull qwen2.5:7b-instruct-q4_K_M
```

Then enable `USE_LLM_SQL=1` and/or `USE_LLM_SUMMARY=1` in `.env`. Both are disabled by default.

## Offline paper reproduction

```bash
pip install -r services/core/requirements.txt
python scripts/reproduce_paper.py
```

The script evaluates representative records entirely in memory and prints the paper configuration's recommendations, AHP priority profiles, and privacy outcomes.

## Development

```bash
pip install -r services/core/requirements.txt -r services/nlp/requirements.txt pytest
python services/core/app.py

QUERY_API_URL=http://your-query-service/api/query python services/nlp/app.py

cd services/nlp-web
npm install
QUERY_API_URL=http://your-query-service/api/query npm run dev
```

## Repository layout

```text
services/
├── core/       # stateless paper analysis API and qprime algorithms
├── nlp/        # natural-language SQL generation and summarisation
└── nlp-web/    # query and visualisation application
scripts/        # offline paper-algorithm reproduction
tests/          # algorithm and NLP tests
docs/           # architecture and design specifications
```

## Citation

This repository accompanies:

> K. S. Jagarlamudi et al., “A Quality- and Privacy-Aware Edge–Cloud Continuum Framework for Internet of Things Applications”, IEEE Access (under review), 2026.

See [CITATION.cff](CITATION.cff).

## License

[MIT](LICENSE)
