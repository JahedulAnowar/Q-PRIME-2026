"""Persistent MongoDB repository for records, policy, and placement evidence."""

import copy
import os
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient, ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError


MONGO_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017")
MONGO_DB = os.getenv("MONGODB_DATABASE", "qprime")

RECORD_FIELDS = [
    {"name": "record_id", "type": "varchar", "hidden": False},
    {"name": "entity", "type": "varchar", "hidden": False},
    {"name": "contextattribute", "type": "varchar", "hidden": False},
    {
        "name": "contextvalue",
        "type": (
            "row(event varchar, person varchar, distance double, temperature double, "
            "humidity double, pressure double, moisture_pct double, smoke_ppm double, bpm double)"
        ),
        "hidden": False,
    },
    {
        "name": "resource",
        "type": (
            "row(device_id varchar, device_name varchar, sensor_id varchar, "
            "gateway_id varchar)"
        ),
        "hidden": False,
    },
    {"name": "timestamp", "type": "bigint", "hidden": False},
    {"name": "ingested_at", "type": "bigint", "hidden": False},
    {"name": "refreshrate", "type": "double", "hidden": False},
    {"name": "source", "type": "varchar", "hidden": False},
    {"name": "recommended_tier", "type": "varchar", "hidden": False},
    {"name": "storage_location", "type": "varchar", "hidden": False},
    {"name": "actual_backend", "type": "varchar", "hidden": False},
    {"name": "cloud_fallback", "type": "boolean", "hidden": False},
    {"name": "pii_detected", "type": "boolean", "hidden": False},
    {"name": "canonical_json", "type": "json", "hidden": False},
]


def utc_ms() -> int:
    return int(time.time() * 1000)


def json_safe(value: Any) -> Any:
    """Return a response-safe deep copy of MongoDB values."""
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


class MongoRepository:
    """Small explicit persistence boundary around the Q-PRIME database."""

    def __init__(self, uri: Optional[str] = None, database: Optional[str] = None):
        self.uri = uri or MONGO_URI
        self.database_name = database or MONGO_DB
        self.client = MongoClient(
            self.uri,
            serverSelectionTimeoutMS=int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "2500")),
            connectTimeoutMS=int(os.getenv("MONGODB_CONNECT_TIMEOUT_MS", "2500")),
            retryWrites=True,
        )
        self.db = self.client[self.database_name]

    def health(self) -> Dict[str, Any]:
        started = utc_ms()
        try:
            self.client.admin.command("ping")
            return {
                "status": "connected",
                "database": self.database_name,
                "latency_ms": utc_ms() - started,
            }
        except PyMongoError as exc:
            return {
                "status": "unavailable",
                "database": self.database_name,
                "error": str(exc),
                "latency_ms": utc_ms() - started,
            }

    def require(self) -> None:
        self.client.admin.command("ping")

    def ensure_indexes(self) -> None:
        self.require()
        for name in ("edge_records", "cloud_records"):
            collection = self.db[name]
            collection.create_index("record_id", unique=True)
            collection.create_index([("timestamp", DESCENDING)])
            collection.create_index([("resource.device_name", ASCENDING), ("timestamp", DESCENDING)])
            collection.create_index([("contextattribute", ASCENDING), ("timestamp", DESCENDING)])
        decisions = self.db.placement_decisions
        decisions.create_index("record_id", unique=True)
        decisions.create_index([("created_at", DESCENDING)])
        decisions.create_index([("device_name", ASCENDING), ("created_at", DESCENDING)])
        decisions.create_index([("contextattribute", ASCENDING), ("created_at", DESCENDING)])
        decisions.create_index([("recommended_tier", ASCENDING), ("created_at", DESCENDING)])
        decisions.create_index([("actual_backends", ASCENDING), ("created_at", DESCENDING)])
        decisions.create_index([("source", ASCENDING), ("created_at", DESCENDING)])
        decisions.create_index([("pii_detected", ASCENDING), ("created_at", DESCENDING)])
        self.db.weight_profiles.create_index(
            [("scope", ASCENDING), ("selector", ASCENDING), ("version", DESCENDING)],
            unique=True,
        )
        self.db.weight_profiles.create_index(
            [("scope", ASCENDING), ("selector", ASCENDING), ("active", ASCENDING)]
        )
        self.db.configuration_history.create_index([("created_at", DESCENDING)])
        self.db.cloud_configuration.create_index([("updated_at", DESCENDING)])
        self.db.qoc_baselines.create_index("baseline_key", unique=True)
        self.db.query_metrics.create_index([("created_at", DESCENDING)])
        self._ensure_presto_schema()

    def _ensure_presto_schema(self) -> None:
        for table in ("edge_records", "cloud_records"):
            self.db["_schema"].replace_one(
                {"table": table},
                {"table": table, "fields": copy.deepcopy(RECORD_FIELDS)},
                upsert=True,
            )

    def find_decision(self, record_id: str) -> Optional[Dict[str, Any]]:
        document = self.db.placement_decisions.find_one({"record_id": record_id})
        return json_safe(document) if document else None

    def store_record(self, collection: str, document: Dict[str, Any]) -> bool:
        if collection not in ("edge_records", "cloud_records"):
            raise ValueError("invalid record collection")
        try:
            self.db[collection].insert_one(copy.deepcopy(document))
            return True
        except DuplicateKeyError:
            return False

    def store_decision(self, decision: Dict[str, Any]) -> bool:
        try:
            self.db.placement_decisions.insert_one(copy.deepcopy(decision))
            return True
        except DuplicateKeyError:
            return False

    def active_profiles(self) -> List[Dict[str, Any]]:
        documents = self.db.weight_profiles.find({"active": True}).sort(
            [("scope", ASCENDING), ("selector", ASCENDING)]
        )
        return [json_safe(document) for document in documents]

    def active_profile(self, scope: str, selector: str = "") -> Optional[Dict[str, Any]]:
        document = self.db.weight_profiles.find_one(
            {"scope": scope, "selector": selector, "active": True}
        )
        return json_safe(document) if document else None

    def profile_versions(
        self, scope: Optional[str] = None, selector: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        query: Dict[str, Any] = {}
        if scope:
            query["scope"] = scope
        if selector is not None:
            query["selector"] = selector
        documents = self.db.weight_profiles.find(query).sort("created_at", DESCENDING).limit(
            max(1, min(int(limit), 500))
        )
        return [json_safe(document) for document in documents]

    def activate_profile(self, profile: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
        scope = profile["scope"]
        selector = profile.get("selector", "")
        self.db.weight_profiles.update_many(
            {"scope": scope, "selector": selector, "active": True},
            {"$set": {"active": False, "deactivated_at": utc_ms()}},
        )
        document = copy.deepcopy(profile)
        document.update({"selector": selector, "active": True, "created_at": utc_ms()})
        self.db.weight_profiles.insert_one(document)
        self.db.configuration_history.insert_one(copy.deepcopy(audit))
        return json_safe(document)

    def configuration_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        documents = self.db.configuration_history.find({}).sort("created_at", DESCENDING).limit(
            max(1, min(int(limit), 500))
        )
        return [json_safe(document) for document in documents]

    def cloud_configuration(self) -> Optional[Dict[str, Any]]:
        document = self.db.cloud_configuration.find_one({"_id": "active"})
        return json_safe(document) if document else None

    def save_cloud_configuration(self, document: Dict[str, Any], audit: Dict[str, Any]) -> Dict[str, Any]:
        payload = copy.deepcopy(document)
        payload["_id"] = "active"
        self.db.cloud_configuration.replace_one({"_id": "active"}, payload, upsert=True)
        self.db.configuration_history.insert_one(copy.deepcopy(audit))
        return json_safe(payload)

    def get_baseline(self, baseline_key: str) -> Optional[Dict[str, Any]]:
        document = self.db.qoc_baselines.find_one({"baseline_key": baseline_key})
        return json_safe(document) if document else None

    def upsert_baseline(self, baseline_key: str, document: Dict[str, Any]) -> Dict[str, Any]:
        payload = copy.deepcopy(document)
        # Baselines returned to the evaluator are JSON-safe and can therefore
        # carry MongoDB's existing _id as a string. Replacement updates must
        # not send that immutable field back to MongoDB.
        payload.pop("_id", None)
        payload.update({"baseline_key": baseline_key, "updated_at": utc_ms()})
        result = self.db.qoc_baselines.find_one_and_replace(
            {"baseline_key": baseline_key},
            payload,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
        return json_safe(result)

    def invalidate_baselines(self, scope: str, selector: str) -> int:
        if scope == "global":
            result = self.db.qoc_baselines.delete_many({})
        elif scope == "stream":
            result = self.db.qoc_baselines.delete_many({"stream_key": selector})
        else:
            result = self.db.qoc_baselines.delete_many(
                {"$or": [{"device_id": selector}, {"device_name": selector}]}
            )
        return int(result.deleted_count)

    def placements(self, filters: Dict[str, Any], limit: int = 200) -> List[Dict[str, Any]]:
        query = self._decision_filter(filters)
        documents = self.db.placement_decisions.find(query).sort("created_at", DESCENDING).limit(
            max(1, min(int(limit), 1000))
        )
        return [json_safe(document) for document in documents]

    @staticmethod
    def _decision_filter(filters: Dict[str, Any]) -> Dict[str, Any]:
        query: Dict[str, Any] = {}
        mapping = {
            "device": "device_name",
            "stream": "contextattribute",
            "source": "source",
            "recommendation": "recommended_tier",
            "backend": "actual_backends",
        }
        for source_key, mongo_key in mapping.items():
            value = filters.get(source_key)
            if value:
                query[mongo_key] = value
        if filters.get("pii") is not None:
            query["pii_detected"] = bool(filters["pii"])
        created: Dict[str, int] = {}
        if filters.get("from_ms") is not None:
            created["$gte"] = int(filters["from_ms"])
        if filters.get("to_ms") is not None:
            created["$lte"] = int(filters["to_ms"])
        if created:
            query["created_at"] = created
        return query

    def record_count(self, collection: str) -> int:
        return int(self.db[collection].count_documents({}))

    def aggregate(self, collection: str, pipeline: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [json_safe(document) for document in self.db[collection].aggregate(list(pipeline))]

    def store_query_metric(self, metric: Dict[str, Any]) -> None:
        self.db.query_metrics.insert_one(copy.deepcopy(metric))


repository = MongoRepository()
