"""Versioned public domain models."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

SCHEMA_VERSION = "1.0"
ANALYTICS_VERSION = "1.0"
REPORT_VERSION = "1.0"
METRICA_SOURCE_URL = "https://github.com/metrica-sports/sample-data"
METRICA_ATTRIBUTION = "Tracking and event data provided by Metrica Sports sample data."


class TeamSide(StrEnum):
    HOME = "Home"
    AWAY = "Away"


class MetricKind(StrEnum):
    PASSING_NETWORK = "passing_network"
    COMPACTNESS = "defensive_compactness"
    PRESSING = "pressing_patterns"
    PITCH_CONTROL = "pitch_control"
    SPACE_CREATION = "space_creation"
    TRANSITIONS = "transition_opportunities"


class Point(BaseModel):
    model_config = ConfigDict(frozen=True)
    x: float = Field(ge=0, le=105)
    y: float = Field(ge=0, le=68)


class PlayerPosition(BaseModel):
    model_config = ConfigDict(frozen=True)
    team: TeamSide
    player_id: str
    position: Point
    velocity_x: float = 0.0
    velocity_y: float = 0.0
    is_goalkeeper: bool = False


class TrackingFrame(BaseModel):
    model_config = ConfigDict(frozen=True)
    match_id: str
    frame_id: int = Field(ge=0)
    period: int = Field(ge=1, le=5)
    timestamp: float = Field(ge=0)
    ball: Point | None = None
    players: list[PlayerPosition]


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)
    event_id: str
    match_id: str
    period: int = Field(ge=1, le=5)
    timestamp: float = Field(ge=0)
    frame_id: int | None = Field(default=None, ge=0)
    team: TeamSide
    player_id: str | None = None
    event_type: str
    subtype: str | None = None
    start: Point | None = None
    end: Point | None = None
    outcome: str | None = None


class Match(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: str = SCHEMA_VERSION
    match_id: str
    name: str
    home_team: str = "Home"
    away_team: str = "Away"
    pitch_length: float = 105.0
    pitch_width: float = 68.0
    tracking_fps: float = Field(default=25.0, gt=0)
    source_url: str = METRICA_SOURCE_URL
    source_attribution: str = METRICA_ATTRIBUTION
    source_checksum: str | None = None
    format: Literal["metrica_csv", "fifa_epts"]


class Possession(BaseModel):
    model_config = ConfigDict(frozen=True)
    possession_id: str
    match_id: str
    team: TeamSide
    period: int
    start_time: float
    end_time: float
    start_frame: int
    end_frame: int
    event_ids: list[str]
    start: Point | None = None
    end: Point | None = None
    outcome: str = "retained"

    @model_validator(mode="after")
    def validate_window(self) -> Possession:
        if self.end_time < self.start_time or self.end_frame < self.start_frame:
            raise ValueError("possession end must not precede its start")
        return self


class AnalysisConfiguration(BaseModel):
    """All public assumptions used by the deterministic analytical engine."""

    model_config = ConfigDict(frozen=True)
    version: str = ANALYTICS_VERSION
    pressure_radius_m: float = Field(default=3.0, gt=0)
    pressure_closing_speed_mps: float = Field(default=1.0, ge=0)
    coordinated_pressure_players: int = Field(default=2, ge=1)
    regain_window_seconds: float = Field(default=5.0, gt=0)
    transition_window_seconds: float = Field(default=10.0, gt=0)
    reaction_time_seconds: float = Field(default=0.7, ge=0)
    max_player_speed_mps: float = Field(default=5.0, gt=0)
    control_time_to_control_attacking: float = Field(default=3.0, gt=0)
    control_time_to_control_defending: float = Field(default=3.0, gt=0)
    pitch_control_grid_x: int = Field(default=32, ge=8, le=80)
    tracking_sample_rate_hz: float = Field(default=5.0, gt=0, le=25)
    epv_goal_weight: float = Field(default=1.0, gt=0)

    @computed_field
    @property
    def configuration_id(self) -> str:
        payload = json.dumps(self.model_dump(exclude={"configuration_id"}), sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


class EvidenceReference(BaseModel):
    model_config = ConfigDict(frozen=True)
    match_id: str
    team: TeamSide
    metric: MetricKind
    metric_version: str = ANALYTICS_VERSION
    possession_id: str
    period: int
    start_frame: int
    end_frame: int
    event_ids: list[str] = Field(default_factory=list)
    score: float | None = None
    supporting: bool = True

    @computed_field
    @property
    def evidence_id(self) -> str:
        polarity = "support" if self.supporting else "counter"
        return f"{self.match_id}:{self.metric.value}:{self.possession_id}:{self.start_frame}-{self.end_frame}:{polarity}"


class MetricResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    metric: MetricKind
    metric_version: str = ANALYTICS_VERSION
    team: TeamSide
    summary: dict[str, Any]
    evidence: list[EvidenceReference]
    caveats: list[str] = Field(default_factory=list)


class TacticalClaim(BaseModel):
    model_config = ConfigDict(frozen=True)
    claim_id: str
    section: MetricKind
    statement: str = Field(min_length=1, max_length=1200)
    confidence: float = Field(ge=0, le=1)
    caveats: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)

    @field_validator("evidence_ids")
    @classmethod
    def unique_evidence(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class TacticalSection(BaseModel):
    model_config = ConfigDict(frozen=True)
    metric: MetricKind
    title: str
    overview: str
    claims: list[TacticalClaim]


class TacticalReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    schema_version: str = REPORT_VERSION
    report_id: str
    match_id: str
    team: TeamSide
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    configuration: AnalysisConfiguration
    model_id: str | None = None
    fallback_used: bool = False
    executive_summary: str
    sections: list[TacticalSection]
    evidence: list[EvidenceReference]
    source_url: str = METRICA_SOURCE_URL
    attribution: str = METRICA_ATTRIBUTION
    methodological_caveats: list[str]

    @model_validator(mode="after")
    def validate_citations(self) -> TacticalReport:
        known = {item.evidence_id for item in self.evidence}
        for section in self.sections:
            for claim in section.claims:
                missing = set(claim.evidence_ids) - known
                if missing:
                    raise ValueError(f"claim {claim.claim_id} cites unknown evidence: {sorted(missing)}")
        return self


class AnalysisRun(BaseModel):
    run_id: str
    match_id: str
    team: TeamSide
    status: Literal["queued", "running", "completed", "failed", "cancelled"] = "queued"
    stages: list[str] = Field(default_factory=list)
    report_id: str | None = None
    error: str | None = None


class EvidenceBundle(BaseModel):
    claim: TacticalClaim
    supporting: list[EvidenceReference]
    contradicting: list[EvidenceReference]
    possessions: list[Possession]
    events: list[Event]
    frames: list[TrackingFrame]


class StageEvent(BaseModel):
    stage: str
    message: str
    progress: float = Field(ge=0, le=1)
    report: TacticalReport | None = None
    error: str | None = None
