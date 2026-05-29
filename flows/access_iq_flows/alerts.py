"""SNS failure alerting hook for Prefect flows."""

from __future__ import annotations

import os

import boto3
import structlog

log = structlog.get_logger(__name__)


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
        flow_run_id = getattr(flow_run, "id", "unknown")
        state_name = getattr(state, "name", "unknown")
        state_message = getattr(state, "message", "")
        sns = boto3.client(
            "sns",
            region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-2"),
        )
        message = (
            f"Access-IQ daily_ingest FAILED\n"
            f"Flow run: {flow_run_id}\n"
            f"State: {state_name} - {state_message}\n"
            f"UI: https://app.prefect.cloud/flow-runs/flow-run/{flow_run_id}"
        )
        sns.publish(
            TopicArn=topic_arn,
            Subject="Access-IQ Pipeline Failure",
            Message=message,
        )
        log.info("sns_alert_sent", topic_arn=topic_arn, flow_run_id=str(flow_run_id))
    except Exception:
        log.warning("sns_alert_failed", exc_info=True)
