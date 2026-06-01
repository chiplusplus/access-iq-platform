"""CDK assertion tests for ObservabilityStack."""

from __future__ import annotations

import pytest

aws_cdk = pytest.importorskip("aws_cdk")
from aws_cdk import App  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

from access_iq_infra.settings import EnvConfig  # noqa: E402
from access_iq_infra.stacks.observability import ObservabilityStack  # noqa: E402


def _cfg(env_name: str = "dev") -> EnvConfig:
    retention = 7 if env_name == "dev" else 90
    return EnvConfig(
        app_name="access-iq",
        env_name=env_name,
        user_name="AWSReservedSSO_test/test",
        account_id="111111111111",
        region="eu-west-2",
        s3={},
        iam={"external_bucket": "x", "trust_account_id": "999999999999"},
        vpc={},
        tags={},
        ecs={},
        obs={"log_retention_days": retention, "alert_email": "test@example.com"},
        redshift={},
        dashboard={},
    )


def _template(env_name: str = "dev") -> Template:
    app = App()
    stack = ObservabilityStack(
        app,
        f"obs-test-{env_name}",
        cfg=_cfg(env_name),
    )
    return Template.from_stack(stack)


def test_six_log_groups() -> None:
    """3 ingestion + 1 pipeline + 1 prefect-server + 1 prefect-worker = 6 (Phase 7)."""
    tpl = _template()
    tpl.resource_count_is("AWS::Logs::LogGroup", 6)


@pytest.mark.parametrize(
    ("env_name", "expected_days"),
    [("dev", 7), ("prod", 90)],
)
def test_log_group_retention(env_name: str, expected_days: int) -> None:
    tpl = _template(env_name)
    tpl.has_resource_properties(
        "AWS::Logs::LogGroup",
        {"RetentionInDays": expected_days},
    )


def test_metric_filters_per_source() -> None:
    """3 ingestion + 1 pipeline = 4 sources, 2 filters each = 8 (prefect excluded)."""
    tpl = _template()
    tpl.resource_count_is("AWS::Logs::MetricFilter", 8)


def test_metric_filter_pattern() -> None:
    tpl = _template()
    filters = tpl.find_resources("AWS::Logs::MetricFilter")
    found = False
    for _lid, res in filters.items():
        pattern = res.get("Properties", {}).get("FilterPattern", "")
        if "status" in pattern and "failed" in pattern:
            found = True
    assert found, "Expected at least one MetricFilter with status/failed pattern"


def test_alarms_per_source() -> None:
    """3 ingestion + 1 pipeline = 4 alarms (prefect excluded from metric filters)."""
    tpl = _template()
    tpl.resource_count_is("AWS::CloudWatch::Alarm", 4)


def test_alarm_has_sns_action() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "AlarmActions": Match.any_value(),
        },
    )


def test_sns_topics_exist() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::SNS::Topic", 2)


def test_dashboard_exists() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::CloudWatch::Dashboard", 1)
