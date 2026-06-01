"""Format CloudWatch alarm JSON into actionable alert messages."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import boto3

_ALARM_DESCRIPTIONS: dict[str, str] = {
    "GEGateFailed": "DATA QUALITY FAILURE (GE gate blocked Gold build)",
    "ValidationError": "VALIDATION ERROR (GE infrastructure failure)",
    "PipelineStaleness": "STALENESS (pipeline has not completed on schedule)",
    "GoldExportStaleness": "STALENESS (Gold export has not completed on schedule)",
}


def handler(event: dict, context: object) -> None:
    sns_client = boto3.client("sns")
    logs_client = boto3.client("logs")
    delivery_arn = os.environ["DELIVERY_TOPIC_ARN"]
    webhook_url = os.environ.get("SLACK_WEBHOOK_URL")

    for record in event.get("Records", []):
        raw = record.get("Sns", {}).get("Message", "{}")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {}

        if payload.get("source") == "prefect":
            summary = _format_prefect(payload)
            subject = _format_prefect_subject(payload)
        elif payload.get("source") == "aws.ecs":
            summary = _format_ecs_event(payload)
            subject = _format_ecs_subject(payload)
        else:
            summary = _format_alarm(payload, logs_client)
            subject = _format_subject(payload)

        sns_client.publish(
            TopicArn=delivery_arn,
            Subject=subject[:100],
            Message=summary,
        )

        if webhook_url:
            _post_slack(webhook_url, subject, summary)


def _format_prefect(payload: dict) -> str:
    flow = payload.get("flow_name", "unknown")
    env = payload.get("env", "unknown")
    state = payload.get("state", "Unknown")
    state_msg = payload.get("state_message", "")
    timestamp = payload.get("timestamp", "unknown")
    time_short = timestamp[:19].replace("T", " ") if timestamp else "unknown"
    ui_link = payload.get("ui_link", "")

    lines = [
        "Type:   PIPELINE FAILURE (Prefect flow)",
        f"Flow:   {flow}",
        f"Env:    {env}",
        f"Time:   {time_short} UTC",
        f"State:  {state}",
    ]
    if state_msg:
        lines.append(f"Detail: {state_msg}")
    lines.append("")
    lines.append("Next steps:")
    if ui_link:
        lines.append(f"  1. Flow run: {ui_link}")
    lines.append(f"  {'2' if ui_link else '1'}. Check logs: /access-iq/{env}/{flow}")
    lines.append(f"  {'3' if ui_link else '2'}. Dashboard: access-iq-{env}-pipeline-health")

    return "\n".join(lines)


def _format_prefect_subject(payload: dict) -> str:
    flow = payload.get("flow_name", "unknown")
    env = payload.get("env", "?")
    return f"[ALERT] {flow} pipeline failed ({env})"


def _format_ecs_event(payload: dict) -> str:
    detail = payload.get("detail", {})
    task_arn = detail.get("taskArn", "unknown")
    task_short = task_arn.rsplit("/", 1)[-1] if "/" in task_arn else task_arn
    stopped_reason = detail.get("stoppedReason", "unknown")
    group = detail.get("group", "unknown")

    containers = detail.get("containers", [])
    container_lines = []
    for c in containers:
        name = c.get("name", "unknown")
        exit_code = c.get("exitCode", "N/A")
        reason = c.get("reason", "")
        line = f"  - {name}: exit={exit_code}"
        if reason:
            line += f" ({reason})"
        container_lines.append(line)

    lines = [
        "Type:   ECS TASK FAILURE",
        f"Task:   {task_short}",
        f"Group:  {group}",
        f"Reason: {stopped_reason}",
    ]
    if container_lines:
        lines.append("Containers:")
        lines.extend(container_lines)

    lines.append("")
    lines.append("Next steps:")
    lines.append("  1. Check ECS task logs in CloudWatch")
    lines.append("  2. If exit=137, increase task memory allocation")
    lines.append("  3. Dashboard: access-iq-infrastructure")

    return "\n".join(lines)


def _format_ecs_subject(payload: dict) -> str:
    detail = payload.get("detail", {})
    group = detail.get("group", "unknown")
    stopped_reason = detail.get("stoppedReason", "")
    label = "OOM" if "OutOfMemory" in stopped_reason or "137" in stopped_reason else "crash"
    return f"[ALERT] ECS task {label} in {group}"


def _format_alarm(alarm: dict, logs_client: object) -> str:
    trigger = alarm.get("Trigger", {})
    metric = trigger.get("MetricName", "Unknown")
    source = metric.split("-", 1)[1] if "-" in metric else metric

    failure_type = _ALARM_DESCRIPTIONS.get(metric)
    if not failure_type:
        if "Crash" in metric:
            failure_type = "CRASH (unhandled exception)"
        elif "Failed" in metric:
            failure_type = "FAILURE (manifest status: failed)"
        else:
            failure_type = "ALERT"

    state = alarm.get("NewStateValue", "Unknown")
    timestamp = alarm.get("StateChangeTime", "")
    time_short = timestamp[:19].replace("T", " ") if timestamp else "unknown"
    env = trigger.get("Namespace", "").split("/")[-1] or "unknown"

    is_staleness = "Staleness" in metric
    log_source = "pipeline" if metric in _ALARM_DESCRIPTIONS else source
    error_detail = "" if is_staleness else _fetch_recent_error(logs_client, env, log_source)

    lines = [
        f"Type:   {failure_type}",
        f"Source: {source}",
        f"Env:    {env}",
        f"Time:   {time_short} UTC",
        f"State:  {state}",
    ]
    if error_detail:
        lines.append(f"Error:  {error_detail}")

    lines.append("")
    lines.append("Next steps:")
    lines.append(f"  1. Check logs: /access-iq/{env}/{log_source}")
    lines.append(f"  2. Dashboard: access-iq-{env}-pipeline-health")

    return "\n".join(lines)


def _fetch_recent_error(logs_client: Any, env: str, source: str) -> str:
    """Query CloudWatch Logs for the most recent crash or failure event."""
    log_group = f"/access-iq/{env}/{source}"
    try:
        resp = logs_client.filter_log_events(
            logGroupName=log_group,
            filterPattern='{ $.event = "ingest_crash" || $.event = "ingest_abort" }',
            limit=1,
            interleaved=True,
        )
        events = resp.get("events", [])
        if not events:
            return ""

        msg = json.loads(events[0]["message"])

        if "exception" in msg:
            tb = msg["exception"]
            last_line = tb.strip().splitlines()[-1]
            return str(last_line)

        if "reason" in msg:
            return str(msg["reason"])

    except Exception:
        return ""
    return ""


def _format_subject(alarm: dict) -> str:
    trigger = alarm.get("Trigger", {})
    metric = trigger.get("MetricName", "Unknown")
    source = metric.split("-", 1)[1] if "-" in metric else metric
    env = trigger.get("Namespace", "").split("/")[-1] or "?"
    state = alarm.get("NewStateValue", "ALARM")

    if state == "OK":
        return f"[RESOLVED] {source} ({env})"

    desc = _ALARM_DESCRIPTIONS.get(metric)
    if desc:
        short = desc.split("(")[0].strip().lower()
        return f"[ALERT] {short} ({env})"
    return f"[ALERT] {source} ingestion failed ({env})"


def _post_slack(url: str, subject: str, body: str) -> None:
    payload = {"text": f":rotating_light: *{subject}*\n```\n{body}\n```"}
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    urllib.request.urlopen(req)
