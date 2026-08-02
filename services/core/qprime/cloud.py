"""Optional AWS write and Athena query adapter for the paper Cloud layer."""

import json
import os
import time
from typing import Any, Dict, List, Optional

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError


def _enabled(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


class AwsCloudAdapter:
    def __init__(self):
        self.enabled = _enabled(os.getenv("AWS_CLOUD_ENABLED"))
        self.mode = os.getenv("AWS_INGEST_MODE", "firehose").strip().lower()
        self.region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "")).strip()
        self.kinesis_stream = os.getenv("AWS_KINESIS_STREAM", "").strip()
        self.firehose_stream = os.getenv("AWS_FIREHOSE_STREAM", "").strip()
        self.athena_database = os.getenv("AWS_ATHENA_DATABASE", "").strip()
        self.athena_table = os.getenv("AWS_ATHENA_TABLE", "").strip()
        self.athena_workgroup = os.getenv("AWS_ATHENA_WORKGROUP", "primary").strip()
        self.athena_output = os.getenv("AWS_ATHENA_OUTPUT", "").strip()
        self.timeout_s = int(os.getenv("AWS_QUERY_TIMEOUT_S", "60"))
        self._last_error: Optional[str] = None
        self._last_write_at: Optional[int] = None
        self._config = Config(
            connect_timeout=3,
            read_timeout=10,
            retries={"max_attempts": 2, "mode": "standard"},
        )

    def configured(self) -> bool:
        if not self.enabled or not self.region:
            return False
        if self.mode == "kinesis":
            return bool(self.kinesis_stream)
        return self.mode == "firehose" and bool(self.firehose_stream)

    def athena_configured(self) -> bool:
        return bool(
            self.configured()
            and self.athena_database
            and self.athena_table
            and self.athena_output
        )

    def health(self, probe: bool = False) -> Dict[str, Any]:
        if not self.configured():
            return {
                "status": "local_fallback",
                "configured": False,
                "mode": "mongodb_cloud_fallback",
            }
        result: Dict[str, Any] = {
            "status": "degraded" if self._last_error else "configured",
            "configured": True,
            "mode": self.mode,
            "region": self.region,
            "athena_configured": self.athena_configured(),
            "last_write_at": self._last_write_at,
            "last_error": self._last_error,
        }
        if not probe:
            return result
        try:
            if self.mode == "kinesis":
                boto3.client("kinesis", region_name=self.region, config=self._config).describe_stream_summary(
                    StreamName=self.kinesis_stream
                )
            else:
                boto3.client("firehose", region_name=self.region, config=self._config).describe_delivery_stream(
                    DeliveryStreamName=self.firehose_stream,
                    Limit=1,
                )
            result["status"] = "connected"
            result["last_error"] = None
        except (BotoCoreError, ClientError) as exc:
            result["status"] = "degraded"
            result["last_error"] = str(exc)
        return result

    def write(self, record: Dict[str, Any]) -> Dict[str, Any]:
        if not self.configured():
            raise RuntimeError("AWS Cloud is not configured")
        data = (json.dumps(record, separators=(",", ":"), default=str) + "\n").encode("utf-8")
        try:
            if self.mode == "kinesis":
                response = boto3.client(
                    "kinesis", region_name=self.region, config=self._config
                ).put_record(
                    StreamName=self.kinesis_stream,
                    Data=data,
                    PartitionKey=str(record.get("record_id") or "qprime"),
                )
                reference = response.get("SequenceNumber")
            else:
                response = boto3.client(
                    "firehose", region_name=self.region, config=self._config
                ).put_record(
                    DeliveryStreamName=self.firehose_stream,
                    Record={"Data": data},
                )
                reference = response.get("RecordId")
            self._last_error = None
            self._last_write_at = int(time.time() * 1000)
            return {"backend": f"aws_{self.mode}", "reference": reference}
        except (BotoCoreError, ClientError) as exc:
            self._last_error = str(exc)
            raise RuntimeError(f"AWS {self.mode} write failed: {exc}") from exc

    def query(self, sql: str) -> List[Dict[str, Any]]:
        if not self.athena_configured():
            raise RuntimeError("AWS Athena is not configured")
        client = boto3.client("athena", region_name=self.region, config=self._config)
        execution = client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={"Database": self.athena_database},
            ResultConfiguration={"OutputLocation": self.athena_output},
            WorkGroup=self.athena_workgroup,
        )
        execution_id = execution["QueryExecutionId"]
        deadline = time.monotonic() + self.timeout_s
        while time.monotonic() < deadline:
            state_payload = client.get_query_execution(QueryExecutionId=execution_id)
            status = state_payload["QueryExecution"]["Status"]
            state = status["State"]
            if state == "SUCCEEDED":
                break
            if state in {"FAILED", "CANCELLED"}:
                reason = status.get("StateChangeReason") or state
                raise RuntimeError(f"Athena query {state.lower()}: {reason}")
            time.sleep(0.25)
        else:
            client.stop_query_execution(QueryExecutionId=execution_id)
            raise RuntimeError("Athena query timed out")

        paginator = client.get_paginator("get_query_results")
        rows: List[List[Optional[str]]] = []
        for page in paginator.paginate(QueryExecutionId=execution_id):
            for row in page["ResultSet"].get("Rows", []):
                rows.append([cell.get("VarCharValue") for cell in row.get("Data", [])])
        if not rows:
            return []
        headers = [str(value or "") for value in rows[0]]
        return [dict(zip(headers, values)) for values in rows[1:]]


cloud_adapter = AwsCloudAdapter()
