from __future__ import annotations

from soccer_tactics.analytics import (
    analyze_match,
    convex_hull,
    epv,
    pitch_control_probability,
    polygon_area,
    validate_evidence,
)
from soccer_tactics.models import AnalysisConfiguration, MetricKind, Point, TeamSide


def test_geometry_and_epv_are_stable():
    hull = convex_hull([Point(x=0, y=0), Point(x=10, y=0), Point(x=10, y=10), Point(x=0, y=10), Point(x=5, y=5)])
    assert polygon_area(hull) == 100
    assert epv(Point(x=90, y=34)) > epv(Point(x=20, y=34))


def test_all_six_metrics_return_valid_evidence(sample_data):
    events, possessions, frames = sample_data
    results = analyze_match(TeamSide.HOME, events, possessions, frames)
    assert {result.metric for result in results} == set(MetricKind)
    validate_evidence(results, possessions)
    assert next(item for item in results if item.metric == MetricKind.PASSING_NETWORK).summary["completed_passes"] == 2


def test_pitch_control_is_a_probability(sample_data):
    _, _, frames = sample_data
    probability = pitch_control_probability(frames[2], Point(x=40, y=34), TeamSide.HOME, AnalysisConfiguration())
    assert 0 <= probability <= 1
