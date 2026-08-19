from __future__ import annotations

import json

from soccer_tactics.data import downsample_tracking, normalize_csv_events
from soccer_tactics.models import Match, TeamSide, TrackingFrame


def test_csv_normalization_retains_endpoints_receiver_and_source_fields(tmp_path):
    event_file = tmp_path / "events.csv"
    event_file.write_text(
        "Team,Type,Subtype,Period,Start Frame,Start Time [s],End Frame,End Time [s],From,To,Start X,Start Y,End X,End Y,Custom Flag\n"
        "Home,PASS,CROSS,1,100,4.0,112,4.48,Player 7,Player 9,0.2,0.4,0.7,0.5,pressured\n",
        encoding="utf-8",
    )

    event = normalize_csv_events("match", event_file)[0]

    assert event.receiver_id == "Player 9"
    assert event.end_frame_id == 112
    assert event.end_timestamp == 4.48
    assert event.outcome_is_inferred is True
    assert json.loads(event.source_attributes_json or "{}")["Custom Flag"] == "pressured"


def test_tracking_downsampling_preserves_original_frame_ids():
    frames = [TrackingFrame(match_id="match", frame_id=index, period=1, timestamp=index / 25, players=[]) for index in range(11)]

    sampled = downsample_tracking(frames, sample_rate_hz=5)

    assert [frame.frame_id for frame in sampled] == [0, 5, 10]
    assert [frame.timestamp for frame in sampled] == [0.0, 0.2, 0.4]


def test_legacy_match_metadata_gets_compatible_ingestion_defaults():
    match = Match.model_validate({"match_id": "legacy", "name": "Legacy", "format": "metrica_csv"})

    assert match.ingestion.analysis_tracking_sample_rate_hz == 5.0
    assert match.ingestion.full_tracking_retained_in_raw is True
    assert match.schema_version == "1.1"
    assert TeamSide.HOME.value == "Home"
