"""Selective SkillCorner Open Data acquisition and normalization."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel

from soccer_tactics.config import Settings, get_settings
from soccer_tactics.models import (
    SKILLCORNER_ATTRIBUTION,
    SKILLCORNER_SOURCE_URL,
    Event,
    IngestionConfiguration,
    Match,
    MatchCapabilities,
    PlayerPosition,
    Point,
    Possession,
    TeamSide,
    TrackingFrame,
)
from soccer_tactics.storage import LocalStore

RAW_BASE = "https://raw.githubusercontent.com/SkillCorner/opendata/master/data"
MEDIA_BASE = "https://media.githubusercontent.com/media/SkillCorner/opendata/master/data"


class SkillCornerCatalogMatch(BaseModel):
    match_id: int
    name: str
    date_time: str
    home_team: str
    away_team: str
    competition_id: int
    season_id: int


def _clock_seconds(value: str | None) -> float:
    if not value:
        return 0.0
    parts = [float(part) for part in value.split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _number(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    return float(value)


def _integer(value: Any, default: int | None = None) -> int | None:
    number = _number(value)
    return int(number) if number is not None else default


def _boolean(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    return str(value).strip().lower() in {"true", "1", "yes"}


def _centered_point(x: Any, y: Any, pitch_length: float = 105.0, pitch_width: float = 68.0) -> Point | None:
    x_value = _number(x)
    y_value = _number(y)
    if x_value is None or y_value is None:
        return None
    return Point(
        x=min(pitch_length, max(0.0, x_value + pitch_length / 2)),
        y=min(pitch_width, max(0.0, y_value + pitch_width / 2)),
    )


class SkillCornerDataService:
    def __init__(self, settings: Settings | None = None, store: LocalStore | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or LocalStore(self.settings)
        self.raw_root = self.settings.raw_dir / "skillcorner"
        self.raw_root.mkdir(parents=True, exist_ok=True)

    def _download(self, url: str, destination: Path, force: bool = False) -> Path:
        if destination.exists() and not force:
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(destination.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        partial.replace(destination)
        return destination

    def catalog(self, refresh: bool = False) -> list[SkillCornerCatalogMatch]:
        path = self._download(f"{RAW_BASE}/matches.json", self.raw_root / "matches.json", force=refresh)
        records = json.loads(path.read_text(encoding="utf-8"))
        return [
            SkillCornerCatalogMatch(
                match_id=item["id"],
                name=f"{item['home_team']['short_name']} vs {item['away_team']['short_name']}",
                date_time=item["date_time"],
                home_team=item["home_team"]["short_name"],
                away_team=item["away_team"]["short_name"],
                competition_id=item["competition_id"],
                season_id=item["season_id"],
            )
            for item in records
        ]

    def sync_raw_match(self, match_id: int, force: bool = False) -> dict[str, Path]:
        directory = self.raw_root / "matches" / str(match_id)
        prefix = f"{RAW_BASE}/matches/{match_id}/{match_id}"
        return {
            "metadata": self._download(f"{prefix}_match.json", directory / f"{match_id}_match.json", force),
            "tracking": self._download(
                f"{MEDIA_BASE}/matches/{match_id}/{match_id}_tracking_extrapolated.jsonl",
                directory / f"{match_id}_tracking_extrapolated.jsonl",
                force,
            ),
            "events": self._download(f"{prefix}_dynamic_events.csv", directory / f"{match_id}_dynamic_events.csv", force),
            "phases": self._download(f"{prefix}_phases_of_play.csv", directory / f"{match_id}_phases_of_play.csv", force),
        }

    @staticmethod
    def _checksum(paths: dict[str, Path]) -> str:
        digest = hashlib.sha256()
        for name, path in sorted(paths.items()):
            digest.update(name.encode())
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _team_maps(metadata: dict[str, Any]) -> tuple[dict[int, TeamSide], dict[int, dict[str, Any]]]:
        team_sides = {
            int(metadata["home_team"]["id"]): TeamSide.HOME,
            int(metadata["away_team"]["id"]): TeamSide.AWAY,
        }
        players = {int(player["id"]): player for player in metadata.get("players", [])}
        return team_sides, players

    def _tracking(
        self,
        match_key: str,
        path: Path,
        metadata: dict[str, Any],
        sample_rate_hz: float,
    ) -> list[TrackingFrame]:
        if not 0 < sample_rate_hz <= 10:
            raise ValueError("SkillCorner analytical sample rate must be greater than 0 and no more than 10 Hz")
        team_sides, players = self._team_maps(metadata)
        pitch_length = float(metadata.get("pitch_length") or 105)
        pitch_width = float(metadata.get("pitch_width") or 68)
        minimum_interval = 1.0 / sample_rate_hz
        previous: dict[tuple[TeamSide, str], tuple[float, Point]] = {}
        last_selected: dict[int, float] = {}
        frames: list[TrackingFrame] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                item = json.loads(line)
                period = _integer(item.get("period"))
                if period is None or not item.get("timestamp"):
                    continue
                timestamp = _clock_seconds(item["timestamp"])
                selected_at = last_selected.get(period)
                if selected_at is not None and timestamp - selected_at < minimum_interval - 1e-6:
                    continue
                last_selected[period] = timestamp
                normalized_players: list[PlayerPosition] = []
                for player_data in item.get("player_data", []):
                    player_id = _integer(player_data.get("player_id"))
                    player = players.get(player_id or -1)
                    if player is None:
                        continue
                    side = team_sides.get(int(player["team_id"]))
                    position = _centered_point(player_data.get("x"), player_data.get("y"), pitch_length, pitch_width)
                    if side is None or position is None:
                        continue
                    identifier = str(player_id)
                    prior = previous.get((side, identifier))
                    velocity_x = velocity_y = 0.0
                    if prior is not None and timestamp > prior[0]:
                        delta = timestamp - prior[0]
                        velocity_x = (position.x - prior[1].x) / delta
                        velocity_y = (position.y - prior[1].y) / delta
                        if (velocity_x**2 + velocity_y**2) ** 0.5 > 12:
                            velocity_x = velocity_y = 0.0
                    previous[(side, identifier)] = (timestamp, position)
                    role = player.get("player_role") or {}
                    normalized_players.append(
                        PlayerPosition(
                            team=side,
                            player_id=identifier,
                            position=position,
                            velocity_x=velocity_x,
                            velocity_y=velocity_y,
                            is_goalkeeper=str(role.get("acronym", "")).upper() == "GK",
                            is_detected=player_data.get("is_detected"),
                        )
                    )
                ball_data = item.get("ball_data") or {}
                possession = item.get("possession") or {}
                group = str(possession.get("group") or "").lower()
                possession_team = TeamSide.HOME if "home" in group else TeamSide.AWAY if "away" in group else None
                frames.append(
                    TrackingFrame(
                        match_id=match_key,
                        frame_id=int(item["frame"]),
                        period=period,
                        timestamp=timestamp,
                        ball=_centered_point(ball_data.get("x"), ball_data.get("y"), pitch_length, pitch_width),
                        ball_z=_number(ball_data.get("z")),
                        ball_is_detected=ball_data.get("is_detected"),
                        possession_team=possession_team,
                        possession_player_id=str(possession["player_id"]) if possession.get("player_id") is not None else None,
                        source_attributes_json=json.dumps(
                            {"image_corners_projection": item.get("image_corners_projection")}, sort_keys=True
                        ),
                        players=normalized_players,
                    )
                )
        return frames

    def _events(self, match_key: str, path: Path, metadata: dict[str, Any]) -> list[Event]:
        team_sides, _ = self._team_maps(metadata)
        events: list[Event] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle)):
                team_id = _integer(row.get("team_id") or row.get("attacking_side_id"))
                side = team_sides.get(team_id or -1)
                if side is None:
                    continue
                provider_type = str(row.get("event_type") or "dynamic_event").strip()
                receiver_id = str(row.get("player_targeted_id") or "").strip() or None
                pass_outcome = str(row.get("pass_outcome") or "").strip()
                event_type = "PASS" if receiver_id or pass_outcome else provider_type.upper()
                start_frame = _integer(row.get("frame_start"), index) or index
                events.append(
                    Event(
                        event_id=f"{match_key}-de{row.get('event_id') or index}",
                        match_id=match_key,
                        period=_integer(row.get("period"), 1) or 1,
                        timestamp=_clock_seconds(row.get("time_start")),
                        frame_id=start_frame,
                        end_frame_id=_integer(row.get("frame_end")),
                        end_timestamp=_clock_seconds(row.get("time_end")) if row.get("time_end") else None,
                        team=side,
                        player_id=str(row.get("player_id") or row.get("player_in_possession_id") or "").strip() or None,
                        receiver_id=receiver_id,
                        event_type=event_type,
                        subtype=str(row.get("event_subtype") or provider_type).strip() or None,
                        start=_centered_point(row.get("x_start"), row.get("y_start")),
                        end=_centered_point(row.get("x_end"), row.get("y_end")),
                        outcome=pass_outcome or str(row.get("end_type") or "").strip() or None,
                        source_attributes_json=json.dumps(row, sort_keys=True),
                    )
                )
        return events

    def _possessions(
        self,
        match_key: str,
        path: Path,
        metadata: dict[str, Any],
        events: list[Event],
    ) -> list[Possession]:
        team_sides, _ = self._team_maps(metadata)
        possessions: list[Possession] = []
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for index, row in enumerate(csv.DictReader(handle), start=1):
                team_id = _integer(row.get("team_in_possession_id"))
                side = team_sides.get(team_id or -1)
                if side is None:
                    continue
                period = _integer(row.get("period"), 1) or 1
                start_frame = _integer(row.get("frame_start"), 0) or 0
                end_frame = _integer(row.get("frame_end"), start_frame) or start_frame
                event_ids = [
                    event.event_id
                    for event in events
                    if event.period == period
                    and event.team == side
                    and event.frame_id is not None
                    and start_frame <= event.frame_id <= end_frame
                ]
                possessions.append(
                    Possession(
                        possession_id=f"{match_key}-phase{index:04d}",
                        match_id=match_key,
                        team=side,
                        period=period,
                        start_time=_clock_seconds(row.get("time_start")),
                        end_time=_clock_seconds(row.get("time_end")),
                        start_frame=start_frame,
                        end_frame=end_frame,
                        event_ids=event_ids,
                        start=_centered_point(row.get("x_start"), row.get("y_start")),
                        end=_centered_point(row.get("x_end"), row.get("y_end")),
                        outcome=str(row.get("team_in_possession_phase_type") or "provider_phase"),
                        derivation_method="skillcorner-phases-of-play-v1",
                        source_attributes_json=json.dumps(row, sort_keys=True),
                    )
                )
        return possessions

    def ingest_match(self, match_id: int, paths: dict[str, Path], sample_rate_hz: float = 5.0) -> Match:
        metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
        match_key = f"skillcorner-{match_id}"
        frames = self._tracking(match_key, paths["tracking"], metadata, sample_rate_hz)
        events = self._events(match_key, paths["events"], metadata)
        possessions = self._possessions(match_key, paths["phases"], metadata, events)
        competition_edition = metadata.get("competition_edition") or {}
        competition = competition_edition.get("competition") or {}
        season = competition_edition.get("season") or {}
        match = Match(
            match_id=match_key,
            name=f"{metadata['home_team']['short_name']} vs {metadata['away_team']['short_name']}",
            home_team=metadata["home_team"]["short_name"],
            away_team=metadata["away_team"]["short_name"],
            tracking_fps=sample_rate_hz,
            source_url=SKILLCORNER_SOURCE_URL,
            source_attribution=SKILLCORNER_ATTRIBUTION,
            source_checksum=self._checksum(paths),
            ingestion=IngestionConfiguration(
                source_tracking_sample_rate_hz=10.0,
                analysis_tracking_sample_rate_hz=sample_rate_hz,
                source_event_attributes_retained=True,
                possession_derivation_method="skillcorner-phases-of-play-v1",
            ),
            capabilities=MatchCapabilities(
                events=True,
                provider_dynamic_events=True,
                continuous_tracking=True,
                ball_tracking=True,
                identified_players=True,
                provider_phases=True,
            ),
            data_provider="skillcorner",
            competition=competition.get("name"),
            season=season.get("name"),
            match_date=metadata.get("date_time"),
            data_quality_caveats=[
                "SkillCorner tracking is inferred from broadcast video and includes extrapolated player positions.",
                "SkillCorner reports approximately 97% player-identity accuracy for this open release.",
                "Dynamic events are provider-derived and are not a conventional synchronized on-ball event feed.",
            ],
            format="skillcorner_jsonl",
        )
        self.store.save_match(match, events, possessions, frames)
        return match

    def sync_match(self, match_id: int, sample_rate_hz: float = 5.0, force: bool = False) -> Match:
        known = {item.match_id for item in self.catalog()}
        if match_id not in known:
            raise KeyError(f"SkillCorner open-data match not found: {match_id}")
        paths = self.sync_raw_match(match_id, force=force)
        return self.ingest_match(match_id, paths, sample_rate_hz=sample_rate_hz)
