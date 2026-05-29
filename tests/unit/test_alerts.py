"""Tests for SNS on_failure alerting hook."""

from __future__ import annotations

import pytest


class TestAlerts:
    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_sns_on_failure_publishes(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_sns_on_failure_skips_without_topic_arn(self): ...

    @pytest.mark.skip(reason="awaiting implementation — Task 3")
    def test_sns_on_failure_degrades_on_error(self): ...
