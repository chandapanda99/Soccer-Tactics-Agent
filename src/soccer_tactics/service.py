"""Application service shared by CLI and HTTP interfaces."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator

from soccer_tactics.agents import ChallengeAnswer, EvidenceBoundHarness
from soccer_tactics.analytics import ANALYTICS, validate_evidence
from soccer_tactics.models import (
    AnalysisConfiguration,
    EvidenceBundle,
    MetricResult,
    StageEvent,
    TacticalReport,
    TeamSide,
)
from soccer_tactics.storage import LocalStore

logger = logging.getLogger("soccer_tactics.service")


class TacticsApplication:
    def __init__(self, store: LocalStore | None = None, harness: EvidenceBoundHarness | None = None) -> None:
        self.store = store or LocalStore()
        self.harness = harness or EvidenceBoundHarness()
        self._cancelled: set[str] = set()

    def cancel(self, run_id: str) -> None:
        self._cancelled.add(run_id)

    def iter_analysis(
        self,
        match_id: str,
        team: TeamSide,
        configuration: AnalysisConfiguration | None = None,
        run_id: str | None = None,
    ) -> Iterator[StageEvent]:
        config = configuration or AnalysisConfiguration()
        run = run_id or str(uuid.uuid4())
        match = self.store.get_match(match_id)
        yield StageEvent(stage="load", message="Loading synchronized events, possessions, and tracking frames", progress=0.02)
        events = self.store.events(match_id)
        possessions = self.store.possessions(match_id)
        frames = self.store.frames(match_id)
        yield StageEvent(stage="load", message="Synchronized match data loaded", progress=0.08)
        results: list[MetricResult] = []
        for index, (kind, function) in enumerate(ANALYTICS.items(), start=1):
            if run in self._cancelled:
                yield StageEvent(stage="cancelled", message="Analysis cancelled", progress=(index - 1) / 8)
                return
            metric_name = kind.value.replace("_", " ")
            yield StageEvent(
                stage=kind.value,
                message=f"Computing {metric_name}",
                progress=0.08 + (index - 1) * 0.1,
            )
            results.append(function(team, events, possessions, frames, config))
            yield StageEvent(
                stage=kind.value,
                message=f"Completed {metric_name}",
                progress=0.08 + index * 0.1,
            )
        yield StageEvent(stage="validation", message="Validating every claimable evidence reference", progress=0.7)
        validate_evidence(results, possessions)
        yield StageEvent(
            stage="synthesis",
            message="Asking the tactical specialists to synthesize the cited report",
            progress=0.76,
        )
        report = self.harness.generate_report(match_id, team, config, results)
        report = report.model_copy(
            update={
                "source_url": match.source_url,
                "attribution": match.source_attribution,
                "methodological_caveats": list(dict.fromkeys([*report.methodological_caveats, *match.data_quality_caveats])),
            }
        )
        self.store.save_report(report)
        logger.info(
            "analysis completed",
            extra={
                "run_id": run,
                "metric_version": config.version,
                "model_id": report.model_id,
                "fallback_used": report.fallback_used,
            },
        )
        yield StageEvent(stage="complete", message="Report ready", progress=1.0, report=report)

    def analyze(self, match_id: str, team: TeamSide, configuration: AnalysisConfiguration | None = None) -> TacticalReport:
        report = None
        for event in self.iter_analysis(match_id, team, configuration):
            if event.report:
                report = event.report
        if report is None:
            raise RuntimeError("analysis ended without a report")
        return report

    def evidence_bundle(self, report_id: str, claim_id: str) -> EvidenceBundle:
        report = self.store.get_report(report_id)
        claims = [claim for section in report.sections for claim in section.claims]
        try:
            claim = next(item for item in claims if item.claim_id == claim_id)
        except StopIteration as error:
            raise KeyError(f"claim not found: {claim_id}") from error
        supporting = [item for item in report.evidence if item.evidence_id in claim.evidence_ids]
        contradicting = [item for item in report.evidence if item.metric == claim.section and not item.supporting]
        references = supporting + contradicting
        possession_ids = {item.possession_id for item in references}
        possessions = [item for item in self.store.possessions(report.match_id) if item.possession_id in possession_ids]
        event_ids = {event_id for item in references for event_id in item.event_ids}
        events = [item for item in self.store.events(report.match_id) if item.event_id in event_ids]
        ranges = [(item.period, item.start_frame, item.end_frame) for item in references]
        frames = [
            frame
            for frame in self.store.frames(report.match_id)
            if any(period == frame.period and start <= frame.frame_id <= end for period, start, end in ranges)
        ]
        return EvidenceBundle(
            claim=claim,
            supporting=supporting,
            contradicting=contradicting,
            possessions=possessions,
            events=events,
            frames=frames,
        )

    def challenge(self, report_id: str, claim_id: str, question: str) -> ChallengeAnswer:
        report = self.store.get_report(report_id)
        bundle = self.evidence_bundle(report_id, claim_id)
        return self.harness.challenge(report, bundle.claim, question)
