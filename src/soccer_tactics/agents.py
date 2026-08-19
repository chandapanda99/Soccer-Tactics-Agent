"""Evidence-bound Deep Agent harness isolated from application services."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langchain.tools import tool
from pydantic import BaseModel, Field

from soccer_tactics.config import Settings, get_settings
from soccer_tactics.models import (
    AnalysisConfiguration,
    MetricKind,
    MetricResult,
    TacticalClaim,
    TacticalReport,
    TacticalSection,
    TeamSide,
)
from soccer_tactics.providers import ModelConfiguration, get_provider
from soccer_tactics.reports import deterministic_report

logger = logging.getLogger("soccer_tactics.agents")


class ReportDraft(BaseModel):
    executive_summary: str = Field(min_length=1, max_length=2500)
    sections: list[TacticalSection] = Field(min_length=6, max_length=6)


class ChallengeAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=2500)
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    limitations: list[str] = Field(default_factory=list, max_length=5)


@dataclass(frozen=True)
class HarnessModel:
    chat_model: Any
    model_id: str


def model_from_settings(settings: Settings | None = None) -> HarnessModel:
    current = settings or get_settings()
    if current.model_provider == "ollama":
        configuration = ModelConfiguration(
            provider="ollama",
            model=current.ollama_model,
            base_url=current.ollama_base_url,
        )
    else:
        if not current.foundry_endpoint:
            raise ValueError("FOUNDRY_ENDPOINT is not configured")
        configuration = ModelConfiguration(
            provider="azure_foundry",
            model=current.model,
            base_url=current.foundry_endpoint,
            api_key=current.foundry_api_key,
            reasoning_effort=current.reasoning_effort,
        )
    provider_model = get_provider(configuration.provider).build(configuration)
    return HarnessModel(provider_model.chat_model, configuration.model_id)


def _tools(results: list[MetricResult]):
    by_metric = {result.metric: result for result in results}
    evidence = {item.evidence_id: item for result in results for item in result.evidence}

    @tool
    def get_metric_summary(metric: str) -> str:
        """Return the complete deterministic summary and caveats for one tactical metric."""
        kind = MetricKind(metric)
        result = by_metric[kind]
        return result.model_dump_json(indent=2)

    @tool
    def rank_possessions(metric: str, supporting: bool = True, limit: int = 5) -> str:
        """Rank possession evidence for or against a metric-level interpretation."""
        kind = MetricKind(metric)
        matches = [item for item in by_metric[kind].evidence if item.supporting == supporting]
        matches.sort(key=lambda item: item.score or 0, reverse=supporting)
        return json.dumps([item.model_dump(mode="json") for item in matches[: max(1, min(limit, 8))]], indent=2)

    @tool
    def verify_evidence(evidence_ids: list[str]) -> str:
        """Verify evidence identifiers before citing them; returns unknown identifiers explicitly."""
        return json.dumps(
            {
                "valid": [item.model_dump(mode="json") for identifier in evidence_ids if (item := evidence.get(identifier))],
                "unknown": [identifier for identifier in evidence_ids if identifier not in evidence],
            },
            indent=2,
        )

    return [get_metric_summary, rank_possessions, verify_evidence]


def _specialists(model: Any, tools: list[Any]) -> list[dict[str, Any]]:
    common = (
        "Interpret only values returned by the read-only tools. Every claim must cite valid evidence IDs. "
        "Never invent observations, players, thresholds, events, or tactical intent. State methodological limitations."
    )
    return [
        {
            "name": "possession-network-analyst",
            "description": "Analyzes passing networks, combinations, progression, and possession structure.",
            "system_prompt": f"{common} Cover only passing_network.",
            "tools": tools,
            "model": model,
        },
        {
            "name": "defensive-pressure-analyst",
            "description": "Analyzes defensive compactness and inferred pressing episodes.",
            "system_prompt": f"{common} Cover only defensive_compactness and pressing_patterns.",
            "tools": tools,
            "model": model,
        },
        {
            "name": "space-transition-analyst",
            "description": "Analyzes pitch control, space creation, and transition opportunities.",
            "system_prompt": f"{common} Cover pitch_control, space_creation, and transition_opportunities.",
            "tools": tools,
            "model": model,
        },
    ]


class EvidenceBoundHarness:
    """Construct Deep Agents per report so no conversation or evidence state leaks between runs."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def generate_report(
        self,
        match_id: str,
        team: TeamSide,
        configuration: AnalysisConfiguration,
        results: list[MetricResult],
    ) -> TacticalReport:
        try:
            resolved = model_from_settings(self.settings)
            tools = _tools(results)
            agent = create_deep_agent(
                model=resolved.chat_model,
                tools=tools,
                system_prompt=(
                    "You are the coordinating soccer tactical analyst. Delegate all six sections to the three named specialists. "
                    "Synthesize without adding facts. Produce exactly one section for each MetricKind. Every claim must contain at least "
                    "one evidence ID returned by a tool, and acknowledge proxy/model limitations."
                ),
                subagents=_specialists(resolved.chat_model, tools),
                response_format=ReportDraft,
                backend=StateBackend(),
                name="soccer-tactics-coordinator",
            )
            result = agent.invoke(
                {
                    "messages": [
                        {
                            "role": "user",
                            "content": (
                                f"Create a six-section tactical report for {team.value} in {match_id}. "
                                f"Analysis configuration: {configuration.configuration_id}. Verify every citation before returning."
                            ),
                        }
                    ]
                }
            )
            draft = result.get("structured_response")
            if not isinstance(draft, ReportDraft):
                draft = ReportDraft.model_validate(draft)
            all_evidence = [item for metric in results for item in metric.evidence]
            report_seed = json.dumps(draft.model_dump(mode="json"), sort_keys=True)
            return TacticalReport(
                report_id=f"report-{hashlib.sha256(report_seed.encode()).hexdigest()[:16]}",
                match_id=match_id,
                team=team,
                configuration=configuration,
                model_id=resolved.model_id,
                fallback_used=False,
                executive_summary=draft.executive_summary,
                sections=draft.sections,
                evidence=all_evidence,
                methodological_caveats=list(dict.fromkeys(caveat for metric in results for caveat in metric.caveats)),
            )
        except Exception as error:
            logger.warning("agent report failed; using deterministic report: %s", " ".join(str(error).split())[:400])
            return deterministic_report(match_id, team, configuration, results, fallback_used=True)

    def challenge(self, report: TacticalReport, claim: TacticalClaim, question: str) -> ChallengeAnswer:
        known = {item.evidence_id: item for item in report.evidence}
        references = [known[identifier] for identifier in claim.evidence_ids if identifier in known]
        counter = [item for item in report.evidence if item.metric == claim.section and not item.supporting][:3]
        fallback = ChallengeAnswer(
            answer=(
                f"The claim is supported by {len(references)} ranked possession windows. Open the cited evidence to inspect the "
                "event timeline and synchronized tracking playback. Counterexamples are included where the metric ranked them lowest."
            ),
            evidence_ids=[item.evidence_id for item in references + counter],
            limitations=claim.caveats,
        )
        try:
            resolved = model_from_settings(self.settings)
            evidence_payload = [item.model_dump(mode="json") for item in references + counter]

            @tool
            def inspect_claim_evidence() -> str:
                """Return all permitted evidence for the challenged claim, including counterexamples."""
                return json.dumps(evidence_payload, indent=2)

            agent = create_deep_agent(
                model=resolved.chat_model,
                tools=[inspect_claim_evidence],
                system_prompt=(
                    "Answer the user's challenge using only inspect_claim_evidence. Cite only returned evidence IDs. "
                    "Distinguish support from counterexamples and do not infer tactical intent."
                ),
                response_format=ChallengeAnswer,
                backend=StateBackend(),
                name="soccer-tactics-challenge",
            )
            result = agent.invoke({"messages": [{"role": "user", "content": f"Claim: {claim.statement}\nChallenge: {question}"}]})
            answer = result.get("structured_response")
            answer = answer if isinstance(answer, ChallengeAnswer) else ChallengeAnswer.model_validate(answer)
            allowed = {item.evidence_id for item in references + counter}
            if not set(answer.evidence_ids) <= allowed:
                raise ValueError("challenge response cited evidence outside the permitted bundle")
            return answer
        except Exception as error:
            logger.warning("agent challenge failed; using deterministic answer: %s", " ".join(str(error).split())[:400])
            return fallback
