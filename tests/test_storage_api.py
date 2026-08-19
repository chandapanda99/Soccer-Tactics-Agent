from __future__ import annotations

from fastapi.testclient import TestClient

from soccer_tactics.agents import EvidenceBoundHarness
from soccer_tactics.api import create_api
from soccer_tactics.config import Settings
from soccer_tactics.data import MetricaDataService
from soccer_tactics.models import TeamSide
from soccer_tactics.service import TacticsApplication


def test_storage_round_trip_and_api_fallback(store):
    assert store.get_match("test-match").name == "Synthetic match"
    assert len(store.frames("test-match")) == 12
    settings = Settings(data_dir=store.settings.data_dir, foundry_endpoint="")
    api = create_api(store=store, settings=settings)
    client = TestClient(api)
    assert client.get("/api/health").json() == {"status": "ready"}
    assert client.get("/api/matches").json()[0]["match_id"] == "test-match"
    with client.stream("POST", "/api/analyses/stream", json={"match_id": "test-match", "team": "Home"}) as response:
        lines = list(response.iter_lines())
    payloads = [__import__("json").loads(line) for line in lines]
    assert payloads[0]["message"] == "Loading synchronized events, possessions, and tracking frames"
    assert any(payload["message"] == "Computing passing network" for payload in payloads)
    assert any(payload["stage"] == "validation" for payload in payloads)
    final = payloads[-1]
    assert final["report"]["fallback_used"] is True
    report_id = final["report"]["report_id"]
    assert client.get(f"/api/reports/{report_id}").status_code == 200

    claim_id = final["report"]["sections"][0]["claims"][0]["claim_id"]
    with client.stream(
        "POST",
        f"/api/reports/{report_id}/claims/{claim_id}/challenge/stream",
        json={"question": "Show the supporting possessions"},
    ) as response:
        challenge_events = [__import__("json").loads(line) for line in response.iter_lines()]
    assert [event["stage"] for event in challenge_events] == ["evidence", "reasoning", "complete"]
    assert challenge_events[-1]["progress"] == 1.0


def test_data_sync_stream_reports_each_game(monkeypatch, store):
    settings = Settings(data_dir=store.settings.data_dir, foundry_endpoint="")
    api = create_api(store=store, settings=settings)
    client = TestClient(api)

    monkeypatch.setattr(MetricaDataService, "sync_raw", lambda self, force=False: self.settings.raw_dir)
    monkeypatch.setattr(MetricaDataService, "ingest_game", lambda self, game, **kwargs: store.get_match("test-match"))

    with client.stream("POST", "/api/data/sync/stream") as response:
        events = [__import__("json").loads(line) for line in response.iter_lines()]

    assert [event["message"] for event in events if event["message"].startswith("Normalizing")] == [
        "Normalizing sample game 1 of 3",
        "Normalizing sample game 2 of 3",
        "Normalizing sample game 3 of 3",
    ]
    assert events[-1]["stage"] == "complete"
    assert events[-1]["progress"] == 1.0


def test_challenge_conversation_is_not_persisted(store):
    application = TacticsApplication(store, EvidenceBoundHarness(Settings(data_dir=store.settings.data_dir, foundry_endpoint="")))
    report = application.analyze("test-match", TeamSide.HOME)
    claim = next(claim for section in report.sections for claim in section.claims)
    answer = application.challenge(report.report_id, claim.claim_id, "Show the evidence")
    assert answer.evidence_ids
    assert not list(store.settings.reports_dir.glob("*chat*"))


def test_full_tracking_cache_is_optional(store, sample_data):
    events, possessions, frames = sample_data
    match = store.get_match("test-match")

    assert store.full_frames("test-match") == frames
    store.save_match(match, events, possessions, frames[::2], full_frames=frames)

    assert store.frames("test-match") == frames[::2]
    assert store.full_frames("test-match") == frames
