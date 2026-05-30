"""SNS failure alerting hook for Prefect flows."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime

import boto3
import structlog

log = structlog.get_logger(__name__)

_SELF_HOSTED_FALLBACK = "http://prefect-server.access-iq.local:4200"


def _prefect_ui_base() -> str:
    """Derive Prefect UI base URL from PREFECT_API_URL, falling back to self-hosted."""
    api_url = os.environ.get("PREFECT_API_URL", "")
    if api_url:
        return api_url.removesuffix("/api").removesuffix("/")
    return _SELF_HOSTED_FALLBACK


def sns_on_failure(flow: object, flow_run: object, state: object) -> None:
    """Publish pipeline failure to SNS ingestion-alerts topic.

    Called by Prefect when the flow enters FAILED state (after all retries exhausted).
    Degrades gracefully if ALERT_SNS_TOPIC_ARN is not set (per RESEARCH A6).
    """
    topic_arn = os.environ.get("ALERT_SNS_TOPIC_ARN", "")
    if not topic_arn:
        log.warning("sns_alert_skipped", reason="ALERT_SNS_TOPIC_ARN not set")
        return
    try:
        flow_name = getattr(flow, "name", "daily-ingest") if flow else "daily-ingest"
        flow_run_id = getattr(flow_run, "id", "unknown")
        state_name = getattr(state, "name", "unknown")
        state_message = getattr(state, "message", "")
        env = os.environ.get("CDK_ENV", os.environ.get("ENV", "dev"))
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")

        sns = boto3.client(
            "sns",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"),
        )
        message = json.dumps(
            {
                "source": "prefect",
                "flow_name": flow_name,
                "flow_run_id": str(flow_run_id),
                "state": state_name,
                "state_message": state_message,
                "env": env,
                "timestamp": now,
                "ui_link": f"{_prefect_ui_base()}/flow-runs/flow-run/{flow_run_id}",
            }
        )
        sns.publish(
            TopicArn=topic_arn,
            Subject="Access-IQ Pipeline Failure",
            Message=message,
        )
        log.info("sns_alert_sent", topic_arn=topic_arn, flow_run_id=str(flow_run_id))
    except Exception:
        log.warning("sns_alert_failed", exc_info=True)
