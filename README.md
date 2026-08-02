# Q-PRIME

**A Quality- and Privacy-Aware Edge–Cloud Continuum Framework for Internet of Things Applications**

Q-PRIME implements the paper's Quality-of-Context evaluation, privacy analysis, criteria weighting/AHP, and per-record Edge/Cloud placement. It persists placement evidence and edge data in MongoDB, supports optional AWS Cloud storage, exposes a unified read-only SQL surface through PrestoDB/Athena, and includes the NLP query application.

## Architecture

```text
raw data record ─────────────────┐
                                 ├─> Q-PRIME ingestion
real device -> EdgeX -> export ──┘       -> QoC + privacy evaluation
                                         -> profile weights / AHP
                                         -> Edge | Cloud | Both decision
                                         -> MongoDB Edge collection
                                         -> AWS when configured, otherwise MongoDB Cloud fallback

question -> NLP -> read-only SQL -> PrestoDB / Athena -> answer and charts
                                  -> /qprime results and configuration UI
```

Q-PRIME never moves retained fallback records into AWS. Once AWS is configured, new Cloud decisions are written there and Cloud queries are sent there; earlier fallback records remain in MongoDB for history and visualisation.

## Components

| Component | Default URL | Responsibility |
|---|---|---|
| Query application | <http://localhost:3000> | Natural-language/SQL queries and device charts |
| Q-PRIME dashboard | <http://localhost:3000/qprime> | Configuration, QoC, placements, privacy, sensitivity, performance |
| Core API | <http://localhost:5005> | Ingestion, paper algorithms, persistence, query routing, metrics |
| NLP API | <http://localhost:5500> | Natural language to SQL and result summarisation |
| MongoDB 8 | `localhost:27017` | Persistent edge, fallback Cloud, policies, baselines, decisions, audit |
| PrestoDB 0.286 | <http://localhost:8080> | SQL over MongoDB and local continuum union |
| EdgeX 4.0.2 | `localhost:59880–59890` | Real-device integration and event export |

## Quick start

Requirements: Docker 24+ with Compose v2.

```bash
cp .env.example .env
docker compose up -d --build
```

All required services start from this command. MongoDB and EdgeX PostgreSQL data use named volumes and survive container recreation. Ollama is optional:

```bash
docker compose --profile llm up -d ollama
```

## Ingestion

Direct producers send one canonical record to `POST /api/ingest`:

```bash
curl -X POST http://localhost:5005/api/ingest \
  -H 'Content-Type: application/json' \
  -d '{
    "contextAttribute": "door",
    "contextValue": {"event": "opened"},
    "resource": {"device_id": "door-1", "device_name": "Door 1"},
    "refreshRate": 1000,
    "timestamp": 1785312000000
  }'
```

Real devices use the bundled EdgeX services. EdgeX's `http-export` application service forwards events to `POST /api/ingest/edgex`; both entry points run the same paper pipeline. Record IDs are deterministic and repeated deliveries are idempotent.

## Placement and persistence

The paper scores are:

```text
QoC_temporal = mean(timeliness, resolution)
QoC_content  = mean(completeness, correctness, significance)

S_edge  = w_temporal * QoC_temporal + w_privacy * P
S_cloud = w_content  * QoC_content
```

MongoDB database `qprime` contains:

- `edge_records`: records placed at Edge;
- `cloud_records`: locally retained Cloud decisions when AWS is absent or a write fails;
- `placement_decisions`: immutable recommendations, scores, effective profile, and actual backend;
- `weight_profiles` and `configuration_history`: versioned global/stream/device policy and audit history;
- `qoc_baselines`: persistent adaptive QoC state; and
- `query_metrics`: query latency and source evidence.

Configuration resolution is `device → stream → global`. The `/qprime` Configuration tab exposes the complete policy JSON, including direct/per-stream/metric/AHP weights, SLA thresholds, correctness rules, required fields, privacy controls, and adaptive-baseline parameters.

## AWS Cloud

Set `AWS_CLOUD_ENABLED=true` plus the variables in `.env.example`. Writes support Firehose or Kinesis; queries use Athena when its database, table, workgroup, and output location are configured. Credentials use the normal AWS environment/provider chain. Do not commit credentials.

## Querying

The logical table is `qprime.continuum`. The core accepts read-only SQL through:

```http
GET /api/query?query=<SQL>&isCloud=<continuum|false|true>
```

- `false`: MongoDB `edge_records` through PrestoDB;
- `true`: Athena when configured, otherwise MongoDB `cloud_records`; and
- `continuum`: both current sources.

Only one read-only statement targeting the logical table is accepted. Non-aggregate queries receive a server-side row limit.

## Core API

```text
GET  /api/health
POST /api/ingest
POST /api/ingest/edgex
POST /api/analyze
GET  /api/query
GET  /api/config
PUT  /api/config
GET|POST /api/config/profiles
GET  /api/config/history
POST /api/config/ahp
GET  /api/results/{overview,decisions,qoc,privacy,performance}
POST /api/results/sensitivity
```

## Development

```bash
pip install -r services/core/requirements.txt -r services/nlp/requirements.txt
python services/core/app.py

cd services/nlp-web
npm install
npm run dev
```

## Repository layout

```text
infra/presto/   # PrestoDB MongoDB connector configuration
services/core/  # paper algorithms, ingestion, placement, persistence and query API
services/nlp/   # natural-language SQL generation and summarisation
services/nlp-web/ # query application plus separate /qprime dashboard
docs/           # design and implementation specifications
```

## Citation and license

See [CITATION.cff](CITATION.cff). Licensed under the [MIT License](LICENSE).
