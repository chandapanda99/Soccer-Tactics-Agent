"""Typer command-line interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

import typer

from soccer_tactics.api import create_api
from soccer_tactics.config import get_settings
from soccer_tactics.data import MetricaDataService
from soccer_tactics.models import TeamSide
from soccer_tactics.observability import configure_logging
from soccer_tactics.service import TacticsApplication
from soccer_tactics.skillcorner import SkillCornerDataService
from soccer_tactics.storage import LocalStore

app = typer.Typer(help="Evidence-bound soccer tactics analyst", no_args_is_help=True)
data_app = typer.Typer(help="Acquire and inspect open soccer data")
skillcorner_app = typer.Typer(help="Browse and acquire SkillCorner Open Data")
report_app = typer.Typer(help="Export persisted tactical reports")
app.add_typer(data_app, name="data")
data_app.add_typer(skillcorner_app, name="skillcorner")
app.add_typer(report_app, name="report")


@data_app.command("sync")
def data_sync(
    force: Annotated[bool, typer.Option(help="Replace the existing raw cache")] = False,
    sample_rate_hz: Annotated[
        float,
        typer.Option(min=0.1, max=25.0, help="Tracking rate for the analytical Parquet cache"),
    ] = 5.0,
    retain_full_tracking: Annotated[
        bool,
        typer.Option(help="Also write a full-rate frames_full.parquet cache"),
    ] = False,
) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    matches = MetricaDataService(settings).sync(
        force=force,
        sample_rate_hz=sample_rate_hz,
        retain_full_tracking=retain_full_tracking,
    )
    for match in matches:
        typer.echo(f"{match.match_id}: {match.name} ({match.format})")


@data_app.command("inspect")
def data_inspect(match_id: str | None = None) -> None:
    store = LocalStore()
    matches = [store.get_match(match_id)] if match_id else store.list_matches()
    for match in matches:
        typer.echo(
            json.dumps(
                {
                    **match.model_dump(mode="json"),
                    "events": len(store.events(match.match_id)),
                    "possessions": len(store.possessions(match.match_id)),
                    "tracking_frames": len(store.frames(match.match_id)),
                },
                indent=2,
            )
        )


@skillcorner_app.command("catalog")
def skillcorner_catalog(refresh: Annotated[bool, typer.Option(help="Refresh the remote catalog")] = False) -> None:
    for match in SkillCornerDataService().catalog(refresh=refresh):
        typer.echo(f"{match.match_id}: {match.name} ({match.date_time[:10]})")


@skillcorner_app.command("sync")
def skillcorner_sync(
    match_id: int,
    sample_rate_hz: Annotated[
        float,
        typer.Option(min=0.1, max=10.0, help="Tracking rate for the analytical Parquet cache"),
    ] = 5.0,
    force: Annotated[bool, typer.Option(help="Replace locally cached source files")] = False,
) -> None:
    match = SkillCornerDataService().sync_match(match_id, sample_rate_hz=sample_rate_hz, force=force)
    typer.echo(f"{match.match_id}: {match.name} ({match.format})")


@app.command()
def analyze(match_id: str, team: TeamSide) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    report = TacticsApplication().analyze(match_id, team)
    typer.echo(f"Created {report.report_id} ({'fallback' if report.fallback_used else report.model_id})")


@report_app.command("export")
def report_export(
    report_id: str,
    format: Literal["html", "markdown"] = "html",
    output: Annotated[Path | None, typer.Option()] = None,
) -> None:
    path = LocalStore().export_report(report_id, format, output)
    typer.echo(str(path))


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8766, reload: bool = False) -> None:
    import uvicorn

    settings = get_settings()
    configure_logging(settings.log_level)
    frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    if reload:
        uvicorn.run("soccer_tactics.api:create_api", factory=True, host=host, port=port, reload=True)
    else:
        uvicorn.run(create_api(frontend_dist=frontend_dist), host=host, port=port)
