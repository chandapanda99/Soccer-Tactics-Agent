from __future__ import annotations

import json

from soccer_tactics.config import Settings
from soccer_tactics.skillcorner import SkillCornerDataService
from soccer_tactics.storage import LocalStore


def test_skillcorner_match_normalizes_tracking_events_and_provider_phases(tmp_path):
    metadata = {
        "id": 123,
        "date_time": "2025-01-01T00:00:00Z",
        "home_team": {"id": 1, "short_name": "Home FC"},
        "away_team": {"id": 2, "short_name": "Away FC"},
        "competition_edition": {
            "competition": {"name": "A-League"},
            "season": {"name": "2024/2025"},
        },
        "players": [
            {"id": 10, "team_id": 1, "player_role": {"acronym": "GK"}},
            {"id": 11, "team_id": 1, "player_role": {"acronym": "CM"}},
            {"id": 20, "team_id": 2, "player_role": {"acronym": "GK"}},
        ],
    }
    metadata_path = tmp_path / "match.json"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    tracking_path = tmp_path / "tracking.jsonl"
    tracking_path.write_text(
        "\n".join(
            json.dumps(
                {
                    "frame": frame,
                    "timestamp": timestamp,
                    "period": 1,
                    "ball_data": {"x": 0, "y": 0, "z": 0.2, "is_detected": True},
                    "possession": {"player_id": 11, "group": "home team"},
                    "image_corners_projection": {"x_top_left": -52.5},
                    "player_data": [
                        {"x": -40, "y": 0, "player_id": 10, "is_detected": True},
                        {"x": x, "y": 1, "player_id": 11, "is_detected": False},
                        {"x": 35, "y": 0, "player_id": 20, "is_detected": True},
                    ],
                }
            )
            for frame, timestamp, x in ((10, "00:00:00.00", -5), (11, "00:00:00.10", -4.8))
        )
        + "\n",
        encoding="utf-8",
    )
    events_path = tmp_path / "events.csv"
    events_path.write_text(
        "event_id,frame_start,frame_end,time_start,time_end,period,team_id,event_type,event_subtype,player_id,player_targeted_id,pass_outcome,x_start,y_start,x_end,y_end\n"
        "1,10,11,00:00:00.00,00:00:00.10,1,1,player_possession,pass,11,10,complete,-5,1,-40,0\n",
        encoding="utf-8",
    )
    phases_path = tmp_path / "phases.csv"
    phases_path.write_text(
        "frame_start,frame_end,time_start,time_end,period,team_in_possession_id,team_in_possession_phase_type,x_start,y_start,x_end,y_end\n"
        "10,11,00:00:00.00,00:00:00.10,1,1,build_up,-5,1,-40,0\n",
        encoding="utf-8",
    )
    settings = Settings(data_dir=tmp_path / "app-data", foundry_endpoint="")
    store = LocalStore(settings)
    service = SkillCornerDataService(settings, store)

    match = service.ingest_match(
        123,
        {"metadata": metadata_path, "tracking": tracking_path, "events": events_path, "phases": phases_path},
        sample_rate_hz=10,
    )

    assert match.match_id == "skillcorner-123"
    assert match.data_provider == "skillcorner"
    assert match.capabilities.provider_phases is True
    assert match.source_attribution.startswith("Broadcast tracking")
    frames = store.frames(match.match_id)
    assert len(frames) == 2
    assert frames[0].ball is not None and frames[0].ball.x == 52.5
    assert frames[0].possession_team == "Home"
    assert next(player for player in frames[0].players if player.player_id == "11").is_detected is False
    event = store.events(match.match_id)[0]
    assert event.event_type == "PASS"
    assert event.receiver_id == "10"
    possession = store.possessions(match.match_id)[0]
    assert possession.event_ids == [event.event_id]
    assert possession.derivation_method == "skillcorner-phases-of-play-v1"
