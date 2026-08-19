from __future__ import annotations

from pathlib import Path

from soccer_tactics.data import normalize_csv_events, segment_possessions
from soccer_tactics.models import TeamSide


def test_csv_event_normalization_and_possession_segmentation(tmp_path: Path):
    source = tmp_path / "events.csv"
    source.write_text(
        "Team,Type,Subtype,Period,Start Frame,Start Time [s],Start X,Start Y,End X,End Y,From\n"
        "Home,PASS,2,1,10,0.4,0.2,0.5,0.4,0.5,1\n"
        "Away,PASS,3,1,20,0.8,0.6,0.5,0.5,0.5,4\n",
        encoding="utf-8",
    )
    events = normalize_csv_events("m", source)
    possessions = segment_possessions("m", events, [])
    assert events[0].team == TeamSide.HOME
    assert events[0].start.x == 21
    assert len(possessions) == 2
    assert possessions[1].team == TeamSide.AWAY
