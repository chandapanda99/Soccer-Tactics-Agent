import json

import pytest
from pydantic import ValidationError

from soccer_tactics.agents import MetricToolInput, _tools
from soccer_tactics.models import MetricKind, MetricResult, TeamSide


def transition_result() -> MetricResult:
    return MetricResult(
        metric=MetricKind.TRANSITIONS,
        team=TeamSide.AWAY,
        summary={"transition_count": 3},
        evidence=[],
        caveats=[],
    )


def test_metric_tool_schema_exposes_enum_values() -> None:
    schema = MetricToolInput.model_json_schema()

    assert set(schema["$defs"]["MetricKind"]["enum"]) == {metric.value for metric in MetricKind}


def test_metric_tool_recovers_known_metric_from_scoped_argument() -> None:
    scoped = "skillcorner-1925299|8b3b32129e78|Away|transition_opportunities"

    parsed = MetricToolInput.model_validate({"metric": scoped})

    assert parsed.metric is MetricKind.TRANSITIONS


def test_metric_tool_rejects_unknown_scoped_argument() -> None:
    with pytest.raises(ValidationError):
        MetricToolInput.model_validate({"metric": "match|config|Away|unknown_metric"})


def test_summary_tool_accepts_scoped_metric_without_triggering_fallback() -> None:
    summary_tool = _tools([transition_result()])[0]

    payload = summary_tool.invoke(
        {"metric": "skillcorner-1925299|8b3b32129e78|Away|transition_opportunities"}
    )

    assert json.loads(payload)["metric"] == MetricKind.TRANSITIONS.value
