"""ObservabilityStack -- log groups, metric filters, alarms, SNS, dashboard (D-08..D-12)."""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudwatch as cw
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_logs as logs
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subs
from constructs import Construct

from access_iq_infra.settings import EnvConfig

INGESTION_SOURCES = ["ingest-postgres", "ingest-sftp", "ingest-trust-s3"]

RETENTION_MAP: dict[int, logs.RetentionDays] = {
    1: logs.RetentionDays.ONE_DAY,
    3: logs.RetentionDays.THREE_DAYS,
    5: logs.RetentionDays.FIVE_DAYS,
    7: logs.RetentionDays.ONE_WEEK,
    14: logs.RetentionDays.TWO_WEEKS,
    30: logs.RetentionDays.ONE_MONTH,
    60: logs.RetentionDays.TWO_MONTHS,
    90: logs.RetentionDays.THREE_MONTHS,
    120: logs.RetentionDays.FOUR_MONTHS,
    150: logs.RetentionDays.FIVE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
    400: logs.RetentionDays.THIRTEEN_MONTHS,
    545: logs.RetentionDays.EIGHTEEN_MONTHS,
    731: logs.RetentionDays.TWO_YEARS,
    1827: logs.RetentionDays.FIVE_YEARS,
    3653: logs.RetentionDays.TEN_YEARS,
}


class ObservabilityStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        cfg: EnvConfig,
        **kwargs: Any,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        is_prod = cfg.env_name == "prod"

        # -- Section 1: Log Groups (D-08, D-09, REQ-OBS-01) ----------
        log_retention_days = cfg.obs.get("log_retention_days", 7)
        if log_retention_days not in RETENTION_MAP:
            raise ValueError(
                f"Unsupported log_retention_days={log_retention_days}. "
                f"Valid values: {sorted(RETENTION_MAP.keys())}"
            )
        retention = RETENTION_MAP[log_retention_days]

        log_groups: dict[str, logs.LogGroup] = {}
        for source in INGESTION_SOURCES:
            lg = logs.LogGroup(
                self,
                f"LogGroup-{source}",
                log_group_name=f"/access-iq/{cfg.env_name}/{source}",
                retention=retention,
                removal_policy=RemovalPolicy.RETAIN if is_prod else RemovalPolicy.DESTROY,
            )
            log_groups[source] = lg

        self.log_groups = log_groups

        # -- Section 2: SNS Topic (D-10, REQ-OBS-01) ----------
        sns_topic = sns.Topic(
            self,
            "IngestionAlertsTopic",
            topic_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-alerts",
        )

        alert_email = cfg.obs.get("alert_email")
        if alert_email:
            sns_topic.add_subscription(subs.EmailSubscription(alert_email))

        slack_channel_id = cfg.obs.get("slack_channel_id")
        slack_workspace_id = cfg.obs.get("slack_workspace_id")
        if slack_channel_id and slack_workspace_id:
            from aws_cdk import aws_chatbot as chatbot

            chatbot.SlackChannelConfiguration(
                self,
                "SlackChannel",
                slack_channel_configuration_name=f"{cfg.app_name}-{cfg.env_name}-alerts",
                slack_workspace_id=slack_workspace_id,
                slack_channel_id=slack_channel_id,
                notification_topics=[sns_topic],
            )

        self.sns_topic = sns_topic

        # -- Section 3: Metric Filters + Alarms (D-12, REQ-OBS-01) ----------
        metric_namespace = f"AccessIQ/{cfg.env_name}"

        for source, lg in log_groups.items():
            safe_id = "".join(w.capitalize() for w in source.split("-"))

            mf = logs.MetricFilter(
                self,
                f"MetricFilter-{safe_id}",
                log_group=lg,
                filter_pattern=logs.FilterPattern.string_value("$.status", "=", "failed"),
                metric_namespace=metric_namespace,
                metric_name=f"IngestionFailed-{source}",
                metric_value="1",
                default_value=0,
            )

            alarm = cw.Alarm(
                self,
                f"Alarm-{safe_id}",
                metric=mf.metric(statistic="Sum", period=Duration.minutes(5)),
                threshold=1,
                evaluation_periods=1,
                comparison_operator=cw.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
                treat_missing_data=cw.TreatMissingData.NOT_BREACHING,
                alarm_description=f"Ingestion manifest status:failed for {source}",
            )
            alarm.add_alarm_action(cw_actions.SnsAction(sns_topic))

        # -- Section 4: Dashboard (D-11, REQ-OBS-02) ----------
        dashboard = cw.Dashboard(
            self,
            "IngestionDashboard",
            dashboard_name=f"{cfg.app_name}-{cfg.env_name}-ingestion",
        )

        dashboard.add_widgets(
            cw.GraphWidget(
                title="Ingestion Runs - Last 24h",
                view=cw.GraphWidgetView.BAR,
                left=[
                    cw.Metric(
                        namespace=metric_namespace,
                        metric_name=f"IngestionFailed-{src}",
                        statistic="Sum",
                        period=Duration.hours(24),
                    )
                    for src in INGESTION_SOURCES
                ],
                width=24,
                height=6,
            ),
            cw.LogQueryWidget(
                title="Latest Manifest Status",
                log_group_names=[lg.log_group_name for lg in log_groups.values()],
                query_string=(
                    "fields @timestamp, source, status, run_id\n"
                    "| filter ispresent(status)\n"
                    "| sort @timestamp desc\n"
                    "| limit 10"
                ),
                view=cw.LogQueryVisualizationType.TABLE,
                width=12,
                height=6,
            ),
            cw.LogQueryWidget(
                title="Pipeline Lag (Last Successful Ingest)",
                log_group_names=[lg.log_group_name for lg in log_groups.values()],
                query_string=(
                    "fields @timestamp, source, status\n"
                    '| filter status = "success"\n'
                    "| stats max(@timestamp) as latest_success by source\n"
                    "| display source, latest_success"
                ),
                view=cw.LogQueryVisualizationType.TABLE,
                width=12,
                height=6,
            ),
        )

        # -- Section 5: CfnOutputs ----------
        CfnOutput(
            self,
            "IngestionAlertsTopicArn",
            value=sns_topic.topic_arn,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-alerts-arn",
            description="SNS topic ARN for ingestion failure alerts.",
        )
        CfnOutput(
            self,
            "IngestionDashboardName",
            value=dashboard.dashboard_name,
            export_name=f"{cfg.app_name}-{cfg.env_name}-ingestion-dashboard-name",
            description="CloudWatch dashboard name for ingestion monitoring.",
        )
