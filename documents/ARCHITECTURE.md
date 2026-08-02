# Architecture

Q-PRIME has two product boundaries: stateless paper analysis and read-only
querying of externally owned data.

## Analysis flow

```text
caller-owned record
    -> QoC/SLA evaluation
    -> PII detection
    -> direct or AHP-derived weights
    -> Edge/Cloud/Both recommendation
    -> synchronous response
```

The analysis service has no record repository and no output connector.

## Query flow

```text
browser
    -> Next.js query application
       -> NLP API for natural-language questions
       -> QUERY_API_URL for cards and charts
    -> external query API
    -> user-owned edge/cloud data sources
```

The external endpoint executes SQL and returns rows. Q-PRIME only generates
queries, relays read requests, and presents the response.

## Service boundaries

- `services/core`: Flask API plus the QoC, privacy, AHP, configuration, and
  recommendation modules.
- `services/nlp`: Flask API for SQL generation and summarisation.
- `services/nlp-web`: Next.js query and visualisation interface.

There is intentionally no integration or persistence service in this
repository.
