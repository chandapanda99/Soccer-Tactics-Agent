"""Metrica acquisition and normalization through Kloppy."""

from __future__ import annotations

import csv
import hashlib
import io
import logging
import shutil
import zipfile
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import httpx
from kloppy import metrica

from soccer_tactics.config import Settings, get_settings
from soccer_tactics.models import Event, Match, PlayerPosition, Point, Possession, TeamSide, TrackingFrame
from soccer_tactics.storage import LocalStore

logger = logging.getLogger("soccer_tactics.data")
ARCHIVE_URL = "https://github.com/metrica-sports/sample-data/archive/refs/heads/master.zip"


def _checksum_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(path.name.encode())
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    return digest.hexdigest()


def _seconds(value: Any) -> float:
    if value is None:
        return 0.0
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    if hasattr(value, "seconds") and not isinstance(value, (int, float)):
        return float(value.seconds)
    return float(value)


def _period(value: Any) -> int:
    candidate = getattr(value, "id", value)
    if isinstance(candidate, str):
        digits = "".join(character for character in candidate if character.isdigit())
        return int(digits or "1")
    return int(candidate or 1)


def _point(value: Any) -> Point | None:
    if value is None:
        return None
    value = getattr(value, "coordinates", value)
    if value is None:
        return None
    x = float(getattr(value, "x", value[0] if isinstance(value, (tuple, list)) else 0.0))
    y = float(getattr(value, "y", value[1] if isinstance(value, (tuple, list)) else 0.0))
    # Kloppy's metric coordinate system may be centered or normalized depending on source metadata.
    if -53 <= x < 0 or -35 <= y < 0:
        x += 52.5
        y += 34.0
    elif 0 <= x <= 1 and 0 <= y <= 1:
        x *= 105.0
        y *= 68.0
    return Point(x=min(105.0, max(0.0, x)), y=min(68.0, max(0.0, y)))


def _side(value: Any) -> TeamSide:
    ground = getattr(value, "ground", None)
    if ground is not None:
        ground_text = str(getattr(ground, "value", getattr(ground, "name", ground))).lower()
        if "home" in ground_text:
            return TeamSide.HOME
        if "away" in ground_text:
            return TeamSide.AWAY
    text = str(getattr(value, "name", value)).lower()
    return TeamSide.HOME if "home" in text else TeamSide.AWAY


def _player_id(player: Any) -> str:
    return str(getattr(player, "player_id", None) or getattr(player, "jersey_no", None) or getattr(player, "name", player))


def normalize_tracking(match_id: str, dataset: Any) -> list[TrackingFrame]:
    """Convert a Kloppy TrackingDataset to the stable public frame model."""
    normalized: list[TrackingFrame] = []
    previous: dict[tuple[TeamSide, str], tuple[float, Point]] = {}
    for index, frame in enumerate(dataset.frames):
        timestamp = _seconds(getattr(frame, "timestamp", index / 25))
        period = _period(getattr(frame, "period", 1))
        players: list[PlayerPosition] = []
        for player, coordinates in getattr(frame, "players_data", {}).items():
            position = _point(coordinates)
            if position is None:
                continue
            team = _side(getattr(player, "team", "Away"))
            player_id = _player_id(player)
            prior = previous.get((team, player_id))
            velocity_x = velocity_y = 0.0
            if prior is not None and timestamp > prior[0]:
                delta = timestamp - prior[0]
                velocity_x = (position.x - prior[1].x) / delta
                velocity_y = (position.y - prior[1].y) / delta
                speed = (velocity_x**2 + velocity_y**2) ** 0.5
                if speed > 12:  # reject tracking discontinuities and half-time direction flips
                    velocity_x = velocity_y = 0.0
            previous[(team, player_id)] = (timestamp, position)
            position_name = str(getattr(player, "starting_position", "") or "").lower()
            players.append(
                PlayerPosition(
                    team=team,
                    player_id=player_id,
                    position=position,
                    velocity_x=velocity_x,
                    velocity_y=velocity_y,
                    is_goalkeeper="goalkeeper" in position_name or position_name == "gk",
                )
            )
        frame_id = int(getattr(frame, "frame_id", index) or index)
        normalized.append(
            TrackingFrame(
                match_id=match_id,
                frame_id=frame_id,
                period=period,
                timestamp=max(0.0, timestamp),
                ball=_point(getattr(frame, "ball_coordinates", None)),
                players=players,
            )
        )
    return normalized


def _csv_point(row: dict[str, str], prefix: str) -> Point | None:
    try:
        x = float(row[f"{prefix} X"])
        y = float(row[f"{prefix} Y"])
    except KeyError, TypeError, ValueError:
        return None
    return _point((x, y))


def normalize_csv_events(match_id: str, path: Path) -> list[Event]:
    events: list[Event] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for index, row in enumerate(csv.DictReader(handle)):
            team_text = str(row.get("Team", ""))
            if not team_text:
                continue
            period = int(float(row.get("Period") or 1))
            start_frame = int(float(row.get("Start Frame") or index))
            start_time = float(row.get("Start Time [s]") or start_frame / 25)
            event_type = str(row.get("Type") or "UNKNOWN").strip().upper()
            subtype = str(row.get("Subtype") or "").strip() or None
            outcome = "complete" if not subtype or "INCOMPLETE" not in subtype.upper() else "incomplete"
            events.append(
                Event(
                    event_id=f"{match_id}-e{index:05d}",
                    match_id=match_id,
                    period=period,
                    timestamp=max(0.0, start_time),
                    frame_id=start_frame,
                    team=_side(team_text),
                    player_id=str(row.get("From") or "").strip() or None,
                    event_type=event_type,
                    subtype=subtype,
                    start=_csv_point(row, "Start"),
                    end=_csv_point(row, "End"),
                    outcome=outcome,
                )
            )
    return events


def normalize_kloppy_events(match_id: str, dataset: Any) -> list[Event]:
    events: list[Event] = []
    for index, item in enumerate(dataset.events):
        event_type = str(getattr(getattr(item, "event_type", None), "value", getattr(item, "event_type", "UNKNOWN"))).upper()
        result = getattr(item, "result", None)
        events.append(
            Event(
                event_id=str(getattr(item, "event_id", None) or f"{match_id}-e{index:05d}"),
                match_id=match_id,
                period=_period(getattr(item, "period", 1)),
                timestamp=max(0.0, _seconds(getattr(item, "timestamp", 0))),
                frame_id=getattr(item, "frame_id", None),
                team=_side(getattr(item, "team", "Away")),
                player_id=_player_id(getattr(item, "player", "")) or None,
                event_type=event_type,
                subtype=str(getattr(item, "event_name", "")).strip() or None,
                start=_point(getattr(item, "coordinates", None)),
                end=_point(getattr(item, "receiver_coordinates", None)),
                outcome=str(getattr(result, "value", result)) if result is not None else None,
            )
        )
    return events


def segment_possessions(match_id: str, events: list[Event], frames: list[TrackingFrame]) -> list[Possession]:
    """Build transparent event-delimited possession windows."""
    ordered = sorted(events, key=lambda item: (item.period, item.timestamp, item.event_id))
    if not ordered:
        return []
    frame_by_time = sorted(frames, key=lambda frame: (frame.period, frame.timestamp))

    def nearest_frame(event: Event) -> int:
        if event.frame_id is not None:
            return event.frame_id
        candidates = [frame for frame in frame_by_time if frame.period == event.period]
        return min(candidates, key=lambda frame: abs(frame.timestamp - event.timestamp)).frame_id if candidates else 0

    groups: list[list[Event]] = []
    current: list[Event] = []
    for event in ordered:
        restart = current and (event.team != current[-1].team or event.period != current[-1].period)
        if restart:
            groups.append(current)
            current = []
        current.append(event)
        terminal = event.event_type in {"FOUL", "OFFSIDE", "BALL OUT", "OUT", "GOAL"}
        if terminal:
            groups.append(current)
            current = []
    if current:
        groups.append(current)

    possessions: list[Possession] = []
    for index, group in enumerate(groups):
        first, last = group[0], group[-1]
        possessions.append(
            Possession(
                possession_id=f"{match_id}-p{index + 1:04d}",
                match_id=match_id,
                team=first.team,
                period=first.period,
                start_time=first.timestamp,
                end_time=max(first.timestamp, last.timestamp),
                start_frame=nearest_frame(first),
                end_frame=max(nearest_frame(first), nearest_frame(last)),
                event_ids=[event.event_id for event in group],
                start=first.start,
                end=last.end or last.start,
                outcome=last.event_type.lower().replace(" ", "_"),
            )
        )
    return possessions


class MetricaDataService:
    def __init__(self, settings: Settings | None = None, store: LocalStore | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = store or LocalStore(self.settings)

    @property
    def source_root(self) -> Path:
        candidates = list(self.settings.raw_dir.glob("sample-data-*"))
        return candidates[0] if candidates else self.settings.raw_dir / "sample-data-master"

    def sync_raw(self, force: bool = False) -> Path:
        if self.source_root.exists() and not force:
            return self.source_root
        response = httpx.get(ARCHIVE_URL, follow_redirects=True, timeout=120)
        response.raise_for_status()
        digest = hashlib.sha256(response.content).hexdigest()
        if force:
            for candidate in self.settings.raw_dir.glob("sample-data-*"):
                shutil.rmtree(candidate)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extractall(self.settings.raw_dir)
        (self.settings.raw_dir / "SOURCE.sha256").write_text(f"{digest}  {ARCHIVE_URL}\n", encoding="utf-8")
        return self.source_root

    def _paths(self, game: int) -> dict[str, Path]:
        directory = self.source_root / "data" / f"Sample_Game_{game}"
        files = list(directory.iterdir()) if directory.exists() else []

        def find(*tokens: str) -> Path:
            matches = [path for path in files if all(token.lower() in path.name.lower() for token in tokens)]
            if not matches:
                raise FileNotFoundError(f"could not find {'/'.join(tokens)} in {directory}")
            return matches[0]

        if game in (1, 2):
            return {"home": find("tracking", "home"), "away": find("tracking", "away"), "events": find("events")}
        return {"metadata": find("metadata"), "tracking": find("tracking"), "events": find("events")}

    def ingest_game(self, game: int, sample_rate_hz: float = 5.0) -> Match:
        paths = self._paths(game)
        match_id = f"sample-game-{game}"
        sample_fraction = min(1.0, sample_rate_hz / 25.0)
        if game in (1, 2):
            tracking = metrica.load_tracking_csv(
                home_data=paths["home"], away_data=paths["away"], sample_rate=sample_fraction, coordinates="kloppy"
            )
            events = normalize_csv_events(match_id, paths["events"])
            source_format = "metrica_csv"
        else:
            tracking = metrica.load_tracking_epts(
                meta_data=paths["metadata"], raw_data=paths["tracking"], sample_rate=sample_fraction, coordinates="kloppy"
            )
            event_dataset = metrica.load_event(event_data=paths["events"], meta_data=paths["metadata"], coordinates="kloppy")
            events = normalize_kloppy_events(match_id, event_dataset)
            source_format = "fifa_epts"
        frames = normalize_tracking(match_id, tracking)
        possessions = segment_possessions(match_id, events, frames)
        checksum = _checksum_files(paths.values())
        match = Match(
            match_id=match_id,
            name=f"Metrica Sample Game {game}",
            format=source_format,
            tracking_fps=sample_rate_hz,
            source_checksum=checksum,
        )
        self.store.save_match(match, events, possessions, frames)
        return match

    def sync(self, force: bool = False, games: Iterable[int] = (1, 2, 3)) -> list[Match]:
        self.sync_raw(force=force)
        matches = []
        for game in games:
            logger.info("ingesting Metrica sample game %s", game)
            matches.append(self.ingest_game(game))
        return matches
