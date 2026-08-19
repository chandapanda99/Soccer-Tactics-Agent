"""FastAPI interface for the local Svelte application."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from soccer_tactics.agents import ChallengeAnswer
from soccer_tactics.config import Settings, get_settings
from soccer_tactics.data import MetricaDataService
from soccer_tactics.models import AnalysisConfiguration, EvidenceBundle, Match, TacticalReport, TeamSide, TrackingFrame
from soccer_tactics.providers import provider_choices
from soccer_tactics.service import TacticsApplication
from soccer_tactics.storage import LocalStore


class AnalysisRequest(BaseModel):
    match_id: str
    team: TeamSide
    configuration: AnalysisConfiguration = Field(default_factory=AnalysisConfiguration)


class ChallengeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SettingsView(BaseModel):
    provider: str
    model: str
    provider_options: list[tuple[str, str]]
    model_configured: bool
    data_directory: str


def create_api(
    store: LocalStore | None = None,
    settings: Settings | None = None,
    frontend_dist: Path | None = None,
) -> FastAPI:
    current = settings or get_settings()
    local_store = store or LocalStore(current)
    service = TacticsApplication(local_store)
    api = FastAPI(title="Soccer Tactics Agent API", version="1.0.0")
    api.state.tactics = service
    api.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
    )

    @api.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ready"}

    @api.get("/api/settings", response_model=SettingsView)
    def safe_settings() -> SettingsView:
        configured = bool(current.ollama_base_url) if current.model_provider == "ollama" else bool(current.foundry_endpoint)
        model_name = current.ollama_model if current.model_provider == "ollama" else current.model
        return SettingsView(
            provider=current.model_provider,
            model=model_name,
            provider_options=provider_choices(),
            model_configured=configured,
            data_directory=str(current.data_dir),
        )

    @api.get("/api/matches", response_model=list[Match])
    def list_matches() -> list[Match]:
        return local_store.list_matches()

    @api.post("/api/data/sync", response_model=list[Match])
    def sync_data(force: bool = Query(default=False)) -> list[Match]:
        try:
            return MetricaDataService(current, local_store).sync(force=force)
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Metrica sync failed: {error}") from error

    @api.post("/api/data/sync/stream")
    def stream_sync_data(force: bool = Query(default=False)) -> StreamingResponse:
        def stream():
            data_service = MetricaDataService(current, local_store)
            try:
                cached = data_service.source_root.exists() and not force
                yield (
                    json.dumps(
                        {
                            "stage": "source",
                            "message": "Checking the local Metrica cache" if cached else "Downloading the Metrica sample archive",
                            "progress": 0.03,
                        }
                    )
                    + "\n"
                )
                data_service.sync_raw(force=force)
                yield (
                    json.dumps(
                        {
                            "stage": "source",
                            "message": "Metrica source data is ready",
                            "progress": 0.18,
                        }
                    )
                    + "\n"
                )
                matches: list[Match] = []
                for index, game in enumerate((1, 2, 3), start=1):
                    yield (
                        json.dumps(
                            {
                                "stage": f"game-{game}",
                                "message": f"Normalizing sample game {game} of 3",
                                "progress": 0.18 + (index - 1) * 0.25,
                            }
                        )
                        + "\n"
                    )
                    matches.append(data_service.ingest_game(game))
                    yield (
                        json.dumps(
                            {
                                "stage": f"game-{game}",
                                "message": f"Sample game {game} is ready",
                                "progress": 0.18 + index * 0.25,
                            }
                        )
                        + "\n"
                    )
                yield (
                    json.dumps(
                        {
                            "stage": "complete",
                            "message": "All three sample matches are ready",
                            "progress": 1.0,
                            "matches": [match.model_dump(mode="json") for match in matches],
                        }
                    )
                    + "\n"
                )
            except Exception as error:
                yield json.dumps({"stage": "error", "message": "Metrica sync failed", "progress": 1.0, "error": str(error)}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @api.post("/api/analyses/stream")
    def stream_analysis(request: AnalysisRequest) -> StreamingResponse:
        run_id = str(uuid.uuid4())

        def stream():
            try:
                for event in service.iter_analysis(request.match_id, request.team, request.configuration, run_id=run_id):
                    payload = event.model_dump(mode="json")
                    payload["run_id"] = run_id
                    yield json.dumps(payload, default=str) + "\n"
            except KeyError as error:
                yield json.dumps({"stage": "error", "message": str(error), "error": str(error), "run_id": run_id}) + "\n"
            except Exception as error:
                yield (json.dumps({"stage": "error", "message": "Analysis failed", "error": str(error), "run_id": run_id}) + "\n")

        return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"X-Analysis-Run-ID": run_id})

    @api.delete("/api/analyses/{run_id}", status_code=204)
    def cancel_analysis(run_id: str) -> None:
        service.cancel(run_id)

    @api.get("/api/reports", response_model=list[TacticalReport])
    def list_reports() -> list[TacticalReport]:
        return local_store.list_reports()

    @api.get("/api/reports/{report_id}", response_model=TacticalReport)
    def get_report(report_id: str) -> TacticalReport:
        try:
            return local_store.get_report(report_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.get("/api/reports/{report_id}/claims/{claim_id}/evidence", response_model=EvidenceBundle)
    def claim_evidence(report_id: str, claim_id: str) -> EvidenceBundle:
        try:
            return service.evidence_bundle(report_id, claim_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.post("/api/reports/{report_id}/claims/{claim_id}/challenge", response_model=ChallengeAnswer)
    def challenge(report_id: str, claim_id: str, request: ChallengeRequest) -> ChallengeAnswer:
        try:
            return service.challenge(report_id, claim_id, request.question)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @api.post("/api/reports/{report_id}/claims/{claim_id}/challenge/stream")
    def stream_challenge(report_id: str, claim_id: str, request: ChallengeRequest) -> StreamingResponse:
        def stream():
            yield json.dumps({"stage": "evidence", "message": "Collecting supporting and contradicting evidence", "progress": 0.15}) + "\n"
            try:
                yield (
                    json.dumps({"stage": "reasoning", "message": "Asking the specialist to evaluate the challenge", "progress": 0.45})
                    + "\n"
                )
                answer = service.challenge(report_id, claim_id, request.question)
                yield (
                    json.dumps(
                        {
                            "stage": "complete",
                            "message": "Evidence-bound answer ready",
                            "progress": 1.0,
                            "answer": answer.model_dump(mode="json"),
                        }
                    )
                    + "\n"
                )
            except Exception as error:
                yield json.dumps({"stage": "error", "message": "Challenge failed", "progress": 1.0, "error": str(error)}) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    @api.get("/api/matches/{match_id}/tracking", response_model=list[TrackingFrame])
    def tracking_window(
        match_id: str,
        period: int = Query(ge=1, le=5),
        start_frame: int = Query(ge=0),
        end_frame: int = Query(ge=0),
        stride: int = Query(default=1, ge=1, le=25),
    ) -> list[TrackingFrame]:
        if end_frame < start_frame:
            raise HTTPException(status_code=422, detail="end_frame must not precede start_frame")
        try:
            local_store.get_match(match_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        selected = [
            frame for frame in local_store.frames(match_id) if frame.period == period and start_frame <= frame.frame_id <= end_frame
        ]
        return selected[::stride]

    @api.get("/api/reports/{report_id}/export")
    def export_report(report_id: str, format: Literal["html", "markdown"] = "html") -> FileResponse:
        try:
            path = local_store.export_report(report_id, "html" if format == "html" else "markdown")
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        media_type = "text/html" if format == "html" else "text/markdown"
        return FileResponse(path, media_type=media_type, filename=path.name)

    if frontend_dist is not None and (frontend_dist / "index.html").exists():
        api.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
    return api
