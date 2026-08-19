from __future__ import annotations

from pathlib import Path

import pytest

from soccer_tactics.config import Settings
from soccer_tactics.models import (
    Event,
    Match,
    PlayerPosition,
    Point,
    Possession,
    TeamSide,
    TrackingFrame,
)
from soccer_tactics.storage import LocalStore


@pytest.fixture
def sample_data():
    match_id = "test-match"
    frames = []
    for frame_id in range(12):
        timestamp = float(frame_id)
        ball_x = 25 + frame_id * 3
        players = []
        for team, direction in ((TeamSide.HOME, 1), (TeamSide.AWAY, -1)):
            for player in range(1, 7):
                base_x = 18 + player * 5 if team == TeamSide.HOME else 87 - player * 5
                x = base_x + direction * frame_id * 0.7
                y = 8 + player * 8
                if team == TeamSide.HOME and player == 6:
                    x, y = ball_x - 2.0, 34.0
                players.append(
                    PlayerPosition(
                        team=team,
                        player_id=str(player),
                        position=Point(x=max(0, min(105, x)), y=min(68, y)),
                        velocity_x=2.0 if team == TeamSide.HOME else -0.7,
                        velocity_y=0,
                        is_goalkeeper=player == 1,
                    )
                )
        frames.append(
            TrackingFrame(
                match_id=match_id,
                frame_id=frame_id,
                period=1,
                timestamp=timestamp,
                ball=Point(x=min(105, ball_x), y=34),
                players=players,
            )
        )
    events = [
        Event(
            event_id="e1",
            match_id=match_id,
            period=1,
            timestamp=0,
            frame_id=0,
            team=TeamSide.AWAY,
            player_id="2",
            event_type="PASS",
            start=Point(x=20, y=34),
            end=Point(x=24, y=34),
            outcome="complete",
        ),
        Event(
            event_id="e2",
            match_id=match_id,
            period=1,
            timestamp=2,
            frame_id=2,
            team=TeamSide.HOME,
            player_id="6",
            event_type="PASS",
            subtype="5",
            start=Point(x=31, y=34),
            end=Point(x=50, y=30),
            outcome="complete",
        ),
        Event(
            event_id="e3",
            match_id=match_id,
            period=1,
            timestamp=5,
            frame_id=5,
            team=TeamSide.HOME,
            player_id="5",
            event_type="PASS",
            subtype="4",
            start=Point(x=50, y=30),
            end=Point(x=70, y=28),
            outcome="complete",
        ),
        Event(
            event_id="e4",
            match_id=match_id,
            period=1,
            timestamp=8,
            frame_id=8,
            team=TeamSide.AWAY,
            player_id="3",
            event_type="PASS",
            start=Point(x=65, y=34),
            end=Point(x=58, y=34),
            outcome="complete",
        ),
    ]
    possessions = [
        Possession(
            possession_id="p1",
            match_id=match_id,
            team=TeamSide.AWAY,
            period=1,
            start_time=0,
            end_time=1,
            start_frame=0,
            end_frame=1,
            event_ids=["e1"],
            start=Point(x=20, y=34),
            end=Point(x=24, y=34),
        ),
        Possession(
            possession_id="p2",
            match_id=match_id,
            team=TeamSide.HOME,
            period=1,
            start_time=2,
            end_time=7,
            start_frame=2,
            end_frame=7,
            event_ids=["e2", "e3"],
            start=Point(x=31, y=34),
            end=Point(x=70, y=28),
        ),
        Possession(
            possession_id="p3",
            match_id=match_id,
            team=TeamSide.AWAY,
            period=1,
            start_time=8,
            end_time=11,
            start_frame=8,
            end_frame=11,
            event_ids=["e4"],
            start=Point(x=65, y=34),
            end=Point(x=58, y=34),
        ),
    ]
    return events, possessions, frames


@pytest.fixture
def store(tmp_path: Path, sample_data):
    settings = Settings(data_dir=tmp_path, foundry_endpoint="")
    local = LocalStore(settings)
    match = Match(match_id="test-match", name="Synthetic match", format="metrica_csv")
    events, possessions, frames = sample_data
    local.save_match(match, events, possessions, frames)
    return local
