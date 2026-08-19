"""Deterministic report fallback, validation, and exports."""

from __future__ import annotations

import hashlib
import html
import json
from typing import Any

from soccer_tactics.models import (
    AnalysisConfiguration,
    MetricKind,
    MetricResult,
    TacticalClaim,
    TacticalReport,
    TacticalSection,
    TeamSide,
)

TITLES = {
    MetricKind.PASSING_NETWORK: "Passing network",
    MetricKind.COMPACTNESS: "Defensive compactness",
    MetricKind.PRESSING: "Pressing patterns",
    MetricKind.PITCH_CONTROL: "Pitch control",
    MetricKind.SPACE_CREATION: "Space creation",
    MetricKind.TRANSITIONS: "Transition opportunities",
}


def _humanize(value: Any) -> str:
    if isinstance(value, dict):
        return ", ".join(f"{key.replace('_', ' ')} {item}" for key, item in value.items())
    if isinstance(value, list):
        return ", ".join(str(item) for item in value[:5]) or "none"
    return str(value)


def _statement(result: MetricResult) -> str:
    summary = result.summary
    if result.metric == MetricKind.PASSING_NETWORK:
        return (
            f"The team completed {summary['completed_passes']} passes, including {summary['progressive_passes']} progressive passes; "
            f"the passing graph density was {summary['network_density']}."
        )
    if result.metric == MetricKind.COMPACTNESS:
        return (
            f"Out of possession, the sampled block averaged {summary['mean_length_m']} m long and "
            f"{summary['mean_width_m']} m wide, with a {summary['mean_hull_area_m2']} m² outfield hull."
        )
    if result.metric == MetricKind.PRESSING:
        return (
            f"The tracking proxy identified {summary['pressure_frames']} pressure frames and "
            f"{summary['pressures_leading_to_regain']} episodes followed by a regain within {summary['regain_window_seconds']} seconds."
        )
    if result.metric == MetricKind.PITCH_CONTROL:
        return (
            f"Across {summary['evaluated_passes']} evaluated passes, mean control at the target was "
            f"{summary['mean_target_control']:.1%}; {summary['risky_completed_passes']} completed passes targeted sub-50% control space."
        )
    if result.metric == MetricKind.SPACE_CREATION:
        return (
            f"The control-weighted movement model evaluated {summary['evaluated_possessions']} possessions and measured "
            f"{summary['total_control_value_created']} units of space-creation value."
        )
    return (
        f"The team produced {summary['transition_count']} transition windows, averaging {summary['mean_progression_m']} m of forward "
        f"progression and {summary['mean_epv_gain']} control-weighted EPV gain."
    )


def deterministic_report(
    match_id: str,
    team: TeamSide,
    configuration: AnalysisConfiguration,
    results: list[MetricResult],
    model_id: str | None = None,
    fallback_used: bool = True,
) -> TacticalReport:
    evidence = [item for result in results for item in result.evidence]
    sections: list[TacticalSection] = []
    for result in results:
        support = [item.evidence_id for item in result.evidence if item.supporting][:4]
        claims = []
        if support:
            claim_hash = hashlib.sha256(f"{match_id}:{team}:{result.metric}".encode()).hexdigest()[:10]
            claims.append(
                TacticalClaim(
                    claim_id=f"claim-{claim_hash}",
                    section=result.metric,
                    statement=_statement(result),
                    confidence=min(0.9, 0.55 + 0.05 * len(support)),
                    caveats=result.caveats,
                    evidence_ids=support,
                )
            )
        overview = _statement(result) if support else "There was not enough synchronized evidence to make a cited claim."
        sections.append(TacticalSection(metric=result.metric, title=TITLES[result.metric], overview=overview, claims=claims))
    report_seed = json.dumps(
        {
            "match": match_id,
            "team": team,
            "configuration": configuration.configuration_id,
            "sections": [s.model_dump(mode="json") for s in sections],
        },
        sort_keys=True,
    )
    report_id = f"report-{hashlib.sha256(report_seed.encode()).hexdigest()[:16]}"
    caveats = list(dict.fromkeys(caveat for result in results for caveat in result.caveats))
    return TacticalReport(
        report_id=report_id,
        match_id=match_id,
        team=team,
        configuration=configuration,
        model_id=model_id,
        fallback_used=fallback_used,
        executive_summary=(
            f"This evidence-bound report analyzes {team.value} in {match_id}. It contains "
            f"{sum(len(section.claims) for section in sections)} cited tactical claims across six analytical lenses."
        ),
        sections=sections,
        evidence=evidence,
        methodological_caveats=caveats,
    )


def render_markdown(report: TacticalReport) -> str:
    lines = [
        f"# Tactical report — {report.team.value}",
        "",
        report.executive_summary,
        "",
        f"**Match:** {report.match_id}  ",
        f"**Analysis configuration:** `{report.configuration.configuration_id}`  ",
        f"**Model:** {report.model_id or 'deterministic fallback'}",
        "",
    ]
    for section in report.sections:
        lines.extend([f"## {section.title}", "", section.overview, ""])
        for claim in section.claims:
            lines.append(f"- {claim.statement} _Evidence: {', '.join(claim.evidence_ids)}_")
        lines.append("")
    lines.extend(["## Methodological caveats", ""])
    lines.extend(f"- {caveat}" for caveat in report.methodological_caveats)
    lines.extend(["", "## Attribution", "", f"{report.attribution} [{report.source_url}]({report.source_url})", ""])
    return "\n".join(lines)


def render_html(report: TacticalReport) -> str:
    markdown_sections = []
    for section in report.sections:
        claims = "".join(
            f"<li><p>{html.escape(claim.statement)}</p><small>Evidence: {html.escape(', '.join(claim.evidence_ids))}</small></li>"
            for claim in section.claims
        )
        markdown_sections.append(
            f"<section><h2>{html.escape(section.title)}</h2><p>{html.escape(section.overview)}</p><ul>{claims}</ul></section>"
        )
    caveats = "".join(f"<li>{html.escape(caveat)}</li>" for caveat in report.methodological_caveats)
    match_label = html.escape(report.match_id)
    configuration_id = report.configuration.configuration_id
    source_url = html.escape(report.source_url)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Soccer tactical report</title><style>
body{{font:16px/1.55 system-ui,sans-serif;max-width:900px;margin:3rem auto;padding:0 1.5rem;color:#13251d;background:#f6f2e8}}
h1,h2{{font-family:Georgia,serif}}section{{background:#fff;padding:1.25rem 1.5rem;margin:1rem 0;border-left:5px solid #1f7a55}}
small{{color:#50645a}}footer{{margin-top:2rem;padding-top:1rem;border-top:1px solid #b9c6be}}
</style></head><body><header><h1>Tactical report — {html.escape(report.team.value)}</h1>
<p>{html.escape(report.executive_summary)}</p><small>{match_label} · configuration {configuration_id}</small></header>
{"".join(markdown_sections)}<section><h2>Methodological caveats</h2><ul>{caveats}</ul></section>
<footer>{html.escape(report.attribution)} <a href="{source_url}">Source</a></footer></body></html>"""
