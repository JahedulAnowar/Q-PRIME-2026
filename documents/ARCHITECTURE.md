# Architecture

Q-PRIME owns the paper-processing path after a raw record is produced.

```text
direct ingress ──────────────┐
                            ├─> normalise -> QoC baseline/evaluation -> privacy -> weights/AHP
device -> EdgeX -> HTTP ─────┘                                           |
                                                                          v
                                                            Edge | Cloud | Both
                                                              |              |
                                                        MongoDB Edge   AWS or MongoDB
                                                                       Cloud fallback
```

The decision and effective policy version are always retained in MongoDB. Edge and local Cloud records are exposed to PrestoDB through separate collections. When AWS is configured, new Cloud writes use Kinesis or Firehose and Cloud reads use Athena. Existing local fallback data is not copied or replayed to AWS.

The NLP and web applications query only the logical `qprime.continuum` table. The core validates the SQL and selects the appropriate physical source for Edge, Cloud, or continuum scope. `/qprime` is a separate route in the web application and reads dashboard projections from the core API.

Policy is versioned at global, stream, and device scope. Resolution order is device, then stream, then global. QoC baselines, configuration audit history, placement decisions, and query metrics persist with the MongoDB volume.
