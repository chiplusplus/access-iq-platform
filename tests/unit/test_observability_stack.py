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
        obs={
            "log_retention_days": retention,
            "alert_email": "test@example.com",
            "staleness_alarm_hours": 48,
            "export_staleness_alarm_hours": 50,
        },
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
    """8 status-based (4 sources x 2) + 7 pipeline event-based = 15."""
    tpl = _template()
    tpl.resource_count_is("AWS::Logs::MetricFilter", 15)


def test_metric_filter_pattern() -> None:
    tpl = _template()
    filters = tpl.find_resources("AWS::Logs::MetricFilter")
    found = False
    for _lid, res in filters.items():
        pattern = res.get("Properties", {}).get("FilterPattern", "")
        if "status" in pattern and "failed" in pattern:
            found = True
    assert found, "Expected at least one MetricFilter with status/failed pattern"


def test_pipeline_event_metric_filters() -> None:
    """Pipeline event filters target event names like ge_gate_failed, pipeline_complete."""
    tpl = _template()
    filters = tpl.find_resources("AWS::Logs::MetricFilter")
    event_filters = [
        lid
        for lid, res in filters.items()
        if "event" in res.get("Properties", {}).get("FilterPattern", "")
    ]
    assert len(event_filters) == 7


def test_alarms_per_source() -> None:
    """4 ingestion/pipeline + 4 new (GE gate, validation, staleness x2) = 8."""
    tpl = _template()
    tpl.resource_count_is("AWS::CloudWatch::Alarm", 8)


def test_alarm_has_sns_action() -> None:
    tpl = _template()
    tpl.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {
            "AlarmActions": Match.any_value(),
        },
    )


def test_staleness_alarm_uses_breaching() -> None:
    """Pipeline staleness alarm treats missing data as BREACHING."""
    tpl = _template()
    alarms = tpl.find_resources("AWS::CloudWatch::Alarm")
    breaching_alarms = [
        lid
        for lid, res in alarms.items()
        if res.get("Properties", {}).get("TreatMissingData") == "breaching"
    ]
    assert len(breaching_alarms) == 2, "Expected 2 staleness alarms with BREACHING"


def test_staleness_alarm_evaluation_periods() -> None:
    """Staleness alarm evaluation periods match configured hours."""
    tpl = _template()
    alarms = tpl.find_resources("AWS::CloudWatch::Alarm")
    staleness_alarms = [
        res
        for _, res in alarms.items()
        if res.get("Properties", {}).get("TreatMissingData") == "breaching"
    ]
    periods = sorted(res["Properties"]["EvaluationPeriods"] for res in staleness_alarms)
    assert periods == [48, 50]


def test_ge_gate_alarm() -> None:
    """GE gate failure alarm fires on >= 1 failure in 5 min."""
    tpl = _template()
    alarms = tpl.find_resources("AWS::CloudWatch::Alarm")
    ge_alarms = [
        res
        for _, res in alarms.items()
        if "GE data quality gate failed" in res.get("Properties", {}).get("AlarmDescription", "")
    ]
    assert len(ge_alarms) == 1


def test_sns_topics_exist() -> None:
    tpl = _template()
    tpl.resource_count_is("AWS::SNS::Topic", 2)


def test_four_dashboards() -> None:
    """Pipeline health + ingestion detail + data quality + infrastructure = 4."""
    tpl = _template()
    tpl.resource_count_is("AWS::CloudWatch::Dashboard", 4)


def test_ecs_oom_event_rule() -> None:
    """EventBridge rule for ECS OOM/crash detection."""
    tpl = _template()
    tpl.resource_count_is("AWS::Events::Rule", 1)
    tpl.has_resource_properties(
        "AWS::Events::Rule",
        {
            "EventPattern": Match.object_like(
                {"source": ["aws.ecs"]},
            ),
        },
    )
