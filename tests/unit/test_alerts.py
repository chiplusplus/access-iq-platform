"""Tests for SNS on_failure alerting hook."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from access_iq_flows.alerts import sns_on_failure


class TestAlerts:
    def test_sns_on_failure_publishes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sns_on_failure publishes structured JSON to SNS."""
        monkeypatch.setenv("ALERT_SNS_TOPIC_ARN", "arn:aws:sns:eu-west-2:123456789012:test-topic")
        monkeypatch.setenv("CDK_ENV", "dev")
        mock_sns = MagicMock()
        mock_client = MagicMock(return_value=mock_sns)

        mock_flow = MagicMock()
        mock_flow.name = "daily-ingest"
        mock_flow_run = MagicMock()
        mock_flow_run.id = "abc-123"
        mock_state = MagicMock()
        mock_state.name = "Failed"
        mock_state.message = "boom"

        with patch("access_iq_flows.alerts.boto3.client", mock_client):
            sns_on_failure(flow=mock_flow, flow_run=mock_flow_run, state=mock_state)

        mock_sns.publish.assert_called_once()
        call_kwargs = mock_sns.publish.call_args[1]
        assert call_kwargs["TopicArn"] == "arn:aws:sns:eu-west-2:123456789012:test-topic"

        payload = json.loads(call_kwargs["Message"])
        assert payload["source"] == "prefect"
        assert payload["flow_name"] == "daily-ingest"
        assert payload["flow_run_id"] == "abc-123"
        assert payload["state"] == "Failed"
        assert payload["state_message"] == "boom"
        assert payload["env"] == "dev"
        assert "timestamp" in payload
        assert "ui_link" in payload

    def test_sns_on_failure_skips_without_topic_arn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sns_on_failure skips boto3 call when ALERT_SNS_TOPIC_ARN is not set."""
        monkeypatch.delenv("ALERT_SNS_TOPIC_ARN", raising=False)

        with patch("access_iq_flows.alerts.boto3.client") as mock_client:
            sns_on_failure(flow=None, flow_run=MagicMock(), state=MagicMock())

        mock_client.assert_not_called()

    def test_sns_on_failure_degrades_on_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """sns_on_failure does not raise when boto3 publish fails."""
        monkeypatch.setenv("ALERT_SNS_TOPIC_ARN", "arn:aws:sns:eu-west-2:123456789012:test-topic")
        mock_sns = MagicMock()
        mock_sns.publish.side_effect = Exception("network error")

        with patch("access_iq_flows.alerts.boto3.client", return_value=mock_sns):
            # Must not raise
            sns_on_failure(flow=None, flow_run=MagicMock(), state=MagicMock())
