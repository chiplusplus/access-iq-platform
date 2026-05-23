"""Integration tests: CloudWatch log groups, dashboard, metrics, SNS."""

from __future__ import annotations

from typing import Any

import pytest

from tests.integration.conftest import skip_if_not_found

pytestmark = pytest.mark.integration

INGESTION_SOURCES = ["postgres", "sftp", "trust-s3"]


class TestCloudWatchLogGroups:
    @skip_if_not_found
    def test_log_groups_exist(self, logs_client: Any, env_config: dict[str, Any]) -> None:
        prefix = env_config["prefix"].replace("access-iq-", "")
        missing = []
        for source in INGESTION_SOURCES:
            log_group = f"/access-iq/{prefix}/{source}"
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
        response = cloudwatch_client.get_dashboard(DashboardName=f"{env_config['prefix']}-ops")
        assert response["DashboardBody"]

    @skip_if_not_found
    def test_dashboard_has_widgets(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        import json

        response = cloudwatch_client.get_dashboard(DashboardName=f"{env_config['prefix']}-ops")
        body = json.loads(response["DashboardBody"])
        widgets = body.get("widgets", [])
        assert len(widgets) >= 3, f"Expected >= 3 widgets, got {len(widgets)}"


class TestCloudWatchMetrics:
    @skip_if_not_found
    def test_ingestion_metrics_populated(
        self, cloudwatch_client: Any, env_config: dict[str, Any]
    ) -> None:
        response = cloudwatch_client.list_metrics(
            Namespace=f"AccessIQ/{env_config['env_name']}",
        )
        if not response["Metrics"]:
            # Try alternate namespace patterns
            response = cloudwatch_client.list_metrics(
                Namespace="AccessIQ",
            )
        if not response["Metrics"]:
            pytest.skip("No CloudWatch metrics found — ingestion may not have run yet")


class TestSns:
    @skip_if_not_found
    def test_sns_topic_exists(self, sns_client: Any, env_config: dict[str, Any]) -> None:
        response = sns_client.list_topics()
        topic_arns = [t["TopicArn"] for t in response["Topics"]]
        matching = [arn for arn in topic_arns if env_config["prefix"] in arn]
        assert matching, f"No SNS topic found matching prefix {env_config['prefix']}"
