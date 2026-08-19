from __future__ import annotations

import pytest

from soccer_tactics.analytics import analyze_match
from soccer_tactics.models import AnalysisConfiguration, TacticalReport, TeamSide
from soccer_tactics.reports import deterministic_report, render_html, render_markdown


def test_report_has_six_sections_and_only_known_citations(sample_data):
    events, possessions, frames = sample_data
    results = analyze_match(TeamSide.HOME, events, possessions, frames)
    report = deterministic_report("test-match", TeamSide.HOME, AnalysisConfiguration(), results)
    assert len(report.sections) == 6
    known = {item.evidence_id for item in report.evidence}
    assert all(set(claim.evidence_ids) <= known for section in report.sections for claim in section.claims)
    assert "Metrica" in render_markdown(report)
    assert "<!doctype html>" in render_html(report)


def test_unknown_claim_evidence_is_rejected(sample_data):
    events, possessions, frames = sample_data
    report = deterministic_report(
        "test-match", TeamSide.HOME, AnalysisConfiguration(), analyze_match(TeamSide.HOME, events, possessions, frames)
    )
    payload = report.model_dump(mode="json")
    claim = next(claim for section in payload["sections"] for claim in section["claims"])
    claim["evidence_ids"] = ["invented"]
    with pytest.raises(ValueError, match="unknown evidence"):
        TacticalReport.model_validate(payload)
