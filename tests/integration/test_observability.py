"""Integration tests: CloudWatch log groups, dashboard, metrics, alarms, SNS, Lambda."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration

INGESTION_SOURCES = ["ingest-postgres", "ingest-sftp", "ingest-trust-s3"]


class TestCloudWatchLogGroups:
    @skip_if_not_found
    def test_log_groups_exist(self, logs_client: Any, env_config: dict[str, Any]) -> None:
        env = env_config["env_name"]
        missing = []
        for source in INGESTION_SOURCES:
            log_group = f"/access-iq/{env}/{source}"
            response = logs_client.describe_log_groups(logGroupNamePrefix=log_group)
            if not response["logGroups"]:
                missing.append(log_group)
        assert not missing, f"Missing log groups: {missing}"

    @skip_if_not_found
    def test_log_groups_have_events(self, logs_client: Any, env_config: dict[str, Any]) -> None:
        env = env_config["env_name"]
        empty = []
        for source in INGESTION_SOURCES:
            log_group = f"/access-iq/{env}/{source}"
            try:
                response = logs_client.describe_log_streams(
                    logGroupName=log_group,
                    orderBy="LastEventTime",
                    descending=True,
                    limit=1,
                )
                if not response.get("logStreams"):
                    empty.append(log_group)
            except Exception:
                empty.append(log_group)
        if empty:
            pytest.skip(f"No log events yet in: {empty}")


class TestCloudWatchDashboard:
    @skip_if_not_found
    def test_dashboard_exists(self, cloudwatch_client: Any, env_config: dict[str, Any]) -> None:
        response = cloudwatch_client.get_dashboard(
            DashboardName=f"{env_config['prefix']}-ingestion"
        )
        assert response["DashboardBody"]

    @skip_if_not_found
    def test_dashboard_has_widgets(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        import json

        response = cloudwatch_client.get_dashboard(
            DashboardName=f"{env_config['prefix']}-ingestion"
        )
        body = json.loads(response["DashboardBody"])
        widgets = body.get("widgets", [])
        assert len(widgets) >= 3, f"Expected >= 3 widgets, got {len(widgets)}"


class TestCloudWatchMetricFilters:
    @skip_if_not_found
    def test_metric_filters_exist_per_source(
        self, logs_client: Any, env_config: dict[str, Any]
    ) -> None:
        env = env_config["env_name"]
        missing = []
        for source in INGESTION_SOURCES:
            log_group = f"/access-iq/{env}/{source}"
            response = logs_client.describe_metric_filters(logGroupName=log_group)
            filters = response.get("metricFilters", [])
            filter_names = {mf["metricTransformations"][0]["metricName"] for mf in filters}
            for expected in [f"IngestionFailed-{source}", f"IngestionSuccess-{source}"]:
                if expected not in filter_names:
                    missing.append(expected)
        assert not missing, f"Missing metric filters: {missing}"


class TestCloudWatchAlarms:
    @skip_if_not_found
    def test_ingestion_alarms_exist(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = cloudwatch_client.describe_alarms(
            AlarmNamePrefix=env_config["prefix"],
            MaxRecords=50,
        )
        alarms = response.get("MetricAlarms", [])
        if not alarms:
            response = cloudwatch_client.describe_alarms(MaxRecords=100)
            alarms = [
                a
                for a in response.get("MetricAlarms", [])
                if env_config["env_name"] in a.get("Namespace", "")
            ]
        assert len(alarms) >= 3, (
            f"Expected >= 3 alarms, got {len(alarms)}: {[a['AlarmName'] for a in alarms]}"
        )

    @skip_if_not_found
    def test_alarms_have_sns_action(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = cloudwatch_client.describe_alarms(MaxRecords=100)
        alarms = [
            a
            for a in response.get("MetricAlarms", [])
            if env_config["env_name"] in a.get("Namespace", "")
        ]
        if not alarms:
            pytest.skip("No alarms found")
        for alarm in alarms:
            actions = alarm.get("AlarmActions", [])
            assert actions, f"Alarm '{alarm['AlarmName']}' has no SNS action"


class TestCloudWatchMetrics:
    @skip_if_not_found
    def test_ingestion_metrics_populated(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = cloudwatch_client.list_metrics(
            Namespace=f"AccessIQ/{env_config['env_name']}",
        )
        if not response["Metrics"]:
            pytest.skip("No CloudWatch metrics found — ingestion may not have run yet")


class TestSns:
    @skip_if_not_found
    def test_alert_topic_exists(self, sns_client: Any, env_config: dict[str, Any]) -> None:
        response = sns_client.list_topics()
        topic_arns = [t["TopicArn"] for t in response["Topics"]]
        alert_topic = f"{env_config['prefix']}-ingestion-alerts"
        matching = [arn for arn in topic_arns if alert_topic in arn]
        assert matching, f"No SNS alert topic found matching {alert_topic}"

    @skip_if_not_found
    def test_delivery_topic_exists(self, sns_client: Any, env_config: dict[str, Any]) -> None:
        response = sns_client.list_topics()
        topic_arns = [t["TopicArn"] for t in response["Topics"]]
        delivery_topic = f"{env_config['prefix']}-alert-delivery"
        matching = [arn for arn in topic_arns if delivery_topic in arn]
        assert matching, f"No SNS delivery topic found matching {delivery_topic}"

    @skip_if_not_found
    def test_alert_topic_has_subscription(
        self, sns_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = sns_client.list_topics()
        topic_arns = [t["TopicArn"] for t in response["Topics"]]
        alert_topic = f"{env_config['prefix']}-ingestion-alerts"
        matching = [arn for arn in topic_arns if alert_topic in arn]
        if not matching:
            pytest.skip("Alert topic not found")
        subs = sns_client.list_subscriptions_by_topic(TopicArn=matching[0])
        assert subs["Subscriptions"], "Alert topic has no subscriptions (expected Lambda)"


class TestAlertFormatterLambda:
    @skip_if_not_found
    def test_lambda_exists(self, lambda_client: Any, env_config: dict[str, Any]) -> None:
        response = lambda_client.get_function(
            FunctionName=f"{env_config['prefix']}-alert-formatter"
        )
        config = response["Configuration"]
        assert config["Runtime"] == "python3.12"
        assert config["Handler"] == "index.handler"

    @skip_if_not_found
    def test_lambda_has_delivery_topic_env(
        self, lambda_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = lambda_client.get_function(
            FunctionName=f"{env_config['prefix']}-alert-formatter"
        )
        env_vars = response["Configuration"].get("Environment", {}).get("Variables", {})
        assert "DELIVERY_TOPIC_ARN" in env_vars, "Lambda missing DELIVERY_TOPIC_ARN env var"
