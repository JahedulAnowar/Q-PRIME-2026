"""Read-only placement-aware SQL routing across MongoDB/Presto and Athena."""

import os
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import prestodb
from sqlglot import exp, parse

from .cloud import AwsCloudAdapter, cloud_adapter
from .repository import MongoRepository, repository


LOGICAL_DATABASE = os.getenv("CONTINUUM_DB", "qprime")
LOGICAL_TABLE = os.getenv("CONTINUUM_TABLE", "continuum")
PRESTO_URL = os.getenv("PRESTO_URL", "http://presto:8080")
QUERY_MAX_ROWS = int(os.getenv("QUERY_MAX_ROWS", "1000"))
QUERY_TIMEOUT_S = int(os.getenv("QUERY_TIMEOUT_S", "60"))


def normalize_scope(value: Any) -> str:
    text = str(value or "continuum").strip().lower()
    if text in {"false", "0", "edge"}:
        return "edge"
    if text in {"true", "1", "cloud"}:
        return "cloud"
    return "continuum"


class QueryValidationError(ValueError):
    pass


class QueryRouter:
    def __init__(
        self,
        repo: Optional[MongoRepository] = None,
        cloud: Optional[AwsCloudAdapter] = None,
    ):
        self.repository = repo or repository
        self.cloud = cloud or cloud_adapter

    def health(self) -> Dict[str, Any]:
        parsed = urlparse(PRESTO_URL)
        try:
            connection = prestodb.dbapi.connect(
                host=parsed.hostname or "presto",
                port=parsed.port or 8080,
                user="qprime-health",
                http_scheme=parsed.scheme or "http",
                request_timeout=3,
            )
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            return {"status": "connected", "url": PRESTO_URL}
        except Exception as exc:
            return {"status": "unavailable", "url": PRESTO_URL, "error": str(exc)}

    def execute(self, sql: str, scope_value: Any) -> Dict[str, Any]:
        started = time.perf_counter()
        expression = self._validate(sql)
        scope = normalize_scope(scope_value)
        source = "mongodb"

        if scope == "edge":
            results = self._presto(self._rewrite(expression, "edge_records"))
            edge_rows, cloud_rows = len(results), 0
            sources = ["presto:mongodb.edge_records"]
        elif scope == "cloud" and self.cloud.athena_configured():
            results = self.cloud.query(self._athena_sql(expression))
            edge_rows, cloud_rows = 0, len(results)
            sources = ["athena"]
            source = "aws"
        elif scope == "cloud":
            results = self._presto(self._rewrite(expression, "cloud_records"))
            edge_rows, cloud_rows = 0, len(results)
            sources = ["presto:mongodb.cloud_records"]
        elif self.cloud.athena_configured():
            edge_results = self._presto(self._rewrite(expression, "edge_records"))
            cloud_results = self.cloud.query(self._athena_sql(expression))
            results = self._merge_external(expression, edge_results, cloud_results)
            edge_rows, cloud_rows = len(edge_results), len(cloud_results)
            sources = ["presto:mongodb.edge_records", "athena"]
            source = "federated"
        else:
            edge_results = self._presto(self._rewrite(expression, "edge_records"))
            cloud_results = self._presto(self._rewrite(expression, "cloud_records"))
            results = self._presto(self._rewrite_continuum(expression))
            edge_rows, cloud_rows = len(edge_results), len(cloud_results)
            sources = ["presto:mongodb.edge_records", "presto:mongodb.cloud_records"]

        elapsed = round((time.perf_counter() - started) * 1000, 3)
        metric = {
            "created_at": int(time.time() * 1000),
            "scope": scope,
            "latency_ms": elapsed,
            "result_rows": len(results),
            "edge_rows": edge_rows,
            "cloud_rows": cloud_rows,
            "source": source,
            "success": True,
        }
        self.repository.store_query_metric(metric)
        return {
            "results": results,
            "edge_count": edge_rows,
            "cloud_count": cloud_rows,
            "scope": scope,
            "query_latency_ms": elapsed,
            "sources": sources,
        }

    def _validate(self, sql: str) -> exp.Expression:
        text = str(sql or "").strip()
        if not text:
            raise QueryValidationError("query is empty")
        if "--" in text or "/*" in text or "*/" in text:
            raise QueryValidationError("SQL comments are not allowed")
        try:
            statements = parse(text, read="presto")
        except Exception as exc:
            raise QueryValidationError(f"invalid SQL: {exc}") from exc
        if len(statements) != 1:
            raise QueryValidationError("exactly one SQL statement is allowed")
        expression = statements[0]
        prohibited = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter, exp.Command)
        if isinstance(expression, prohibited) or any(expression.find(kind) for kind in prohibited):
            raise QueryValidationError("only read-only SELECT queries are allowed")
        if not isinstance(expression, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            raise QueryValidationError("only SELECT or WITH ... SELECT is allowed")
        logical_tables = [table for table in expression.find_all(exp.Table) if self._is_logical(table)]
        if not logical_tables:
            raise QueryValidationError(f"query must read {LOGICAL_DATABASE}.{LOGICAL_TABLE}")
        for table in expression.find_all(exp.Table):
            if not self._is_logical(table):
                raise QueryValidationError("query may only access the Q-PRIME logical table")
        if not any(expression.find(kind) for kind in (exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)):
            if expression.args.get("limit") is None:
                expression = expression.limit(QUERY_MAX_ROWS)
        return expression

    @staticmethod
    def _is_logical(table: exp.Table) -> bool:
        return table.name.lower() == LOGICAL_TABLE.lower() and (
            not table.db or table.db.lower() == LOGICAL_DATABASE.lower()
        )

    @staticmethod
    def _physical_table(collection: str) -> exp.Table:
        return exp.to_table(f"mongodb.qprime.{collection}")

    def _rewrite(self, expression: exp.Expression, collection: str) -> str:
        rewritten = expression.copy()
        for table in list(rewritten.find_all(exp.Table)):
            if self._is_logical(table):
                replacement = self._physical_table(collection)
                if table.alias:
                    replacement.set("alias", table.args.get("alias"))
                table.replace(replacement)
        return rewritten.sql(dialect="presto")

    def _rewrite_continuum(self, expression: exp.Expression) -> str:
        rewritten = expression.copy()
        union = exp.union(
            exp.select("*").from_(self._physical_table("edge_records")),
            exp.select("*").from_(self._physical_table("cloud_records")),
            distinct=False,
        )
        for table in list(rewritten.find_all(exp.Table)):
            if self._is_logical(table):
                alias_name = table.alias_or_name or "continuum"
                table.replace(
                    exp.Subquery(
                        this=union.copy(),
                        alias=exp.TableAlias(this=exp.to_identifier(alias_name)),
                    )
                )
        return rewritten.sql(dialect="presto")

    def _athena_sql(self, expression: exp.Expression) -> str:
        rewritten = expression.copy()
        physical = exp.to_table(
            f"{self.cloud.athena_database}.{self.cloud.athena_table}"
        )
        for table in list(rewritten.find_all(exp.Table)):
            if self._is_logical(table):
                replacement = physical.copy()
                if table.alias:
                    replacement.set("alias", table.args.get("alias"))
                table.replace(replacement)
        return rewritten.sql(dialect="presto")

    def _presto(self, sql: str) -> List[Dict[str, Any]]:
        parsed = urlparse(PRESTO_URL)
        connection = prestodb.dbapi.connect(
            host=parsed.hostname or "presto",
            port=parsed.port or 8080,
            user="qprime",
            catalog="mongodb",
            schema="qprime",
            http_scheme=parsed.scheme or "http",
            request_timeout=QUERY_TIMEOUT_S,
        )
        cursor = connection.cursor()
        cursor.execute(sql)
        rows = cursor.fetchall()
        columns = [description[0] for description in cursor.description or []]
        return [dict(zip(columns, row)) for row in rows]

    def _merge_external(
        self,
        expression: exp.Expression,
        edge_rows: List[Dict[str, Any]],
        cloud_rows: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        aggregates = list(
            expression.find_all(exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max)
        )
        if not aggregates:
            merged = edge_rows + cloud_rows
            if merged and "timestamp" in merged[0]:
                merged.sort(key=lambda row: row.get("timestamp") or 0, reverse=True)
            limit = expression.args.get("limit")
            if limit and isinstance(limit.expression, exp.Literal):
                merged = merged[: int(limit.expression.this)]
            return merged[:QUERY_MAX_ROWS]

        if any(isinstance(item, exp.Avg) for item in aggregates):
            raise QueryValidationError(
                "AVG across external Edge/Cloud sources requires an explicit SUM and COUNT query"
            )
        if any(
            isinstance(item, exp.Count) and isinstance(item.this, exp.Distinct)
            for item in aggregates
        ):
            raise QueryValidationError(
                "COUNT DISTINCT across external Edge/Cloud sources is not supported"
            )
        return self._merge_additive_rows(edge_rows, cloud_rows)

    @staticmethod
    def _merge_additive_rows(
        edge_rows: List[Dict[str, Any]], cloud_rows: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        if not edge_rows:
            return cloud_rows
        if not cloud_rows:
            return edge_rows
        numeric_keys = {
            key
            for row in edge_rows + cloud_rows
            for key, value in row.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        }
        group_keys = [key for key in edge_rows[0] if key not in numeric_keys]
        merged: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
        for row in edge_rows + cloud_rows:
            identity = tuple(row.get(key) for key in group_keys)
            target = merged.setdefault(identity, {key: row.get(key) for key in group_keys})
            for key in numeric_keys:
                target[key] = (target.get(key) or 0) + (row.get(key) or 0)
        return list(merged.values())


query_router = QueryRouter()
