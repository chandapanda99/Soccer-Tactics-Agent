"""Local Parquet and report persistence."""

from __future__ import annotations

from pathlib import Path
from typing import TypeVar

import duckdb
import polars as pl
from pydantic import BaseModel

from soccer_tactics.config import Settings, get_settings
from soccer_tactics.models import Event, Match, Possession, TacticalReport, TrackingFrame

ModelT = TypeVar("ModelT", bound=BaseModel)


class LocalStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.ensure_directories()

    def _match_dir(self, match_id: str) -> Path:
        path = self.settings.processed_dir / match_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _write_models(path: Path, values: list[BaseModel]) -> None:
        records = [value.model_dump(mode="json") for value in values]
        if records:
            pl.DataFrame(records, strict=False).write_parquet(path)
        else:
            pl.DataFrame({"_empty": []}).write_parquet(path)

    @staticmethod
    def _read_models(path: Path, model: type[ModelT]) -> list[ModelT]:
        if not path.exists():
            return []
        rows = pl.read_parquet(path).to_dicts()
        return [model.model_validate(row) for row in rows if "_empty" not in row]

    def save_match(
        self,
        match: Match,
        events: list[Event],
        possessions: list[Possession],
        frames: list[TrackingFrame],
    ) -> None:
        directory = self._match_dir(match.match_id)
        (directory / "match.json").write_text(match.model_dump_json(indent=2), encoding="utf-8")
        self._write_models(directory / "events.parquet", events)
        self._write_models(directory / "possessions.parquet", possessions)
        self._write_models(directory / "frames.parquet", frames)

    def list_matches(self) -> list[Match]:
        matches: list[Match] = []
        for path in sorted(self.settings.processed_dir.glob("*/match.json")):
            matches.append(Match.model_validate_json(path.read_text(encoding="utf-8")))
        return matches

    def get_match(self, match_id: str) -> Match:
        path = self._match_dir(match_id) / "match.json"
        if not path.exists():
            raise KeyError(f"match not found: {match_id}; run `soccer-tactics data sync`")
        return Match.model_validate_json(path.read_text(encoding="utf-8"))

    def events(self, match_id: str) -> list[Event]:
        return self._read_models(self._match_dir(match_id) / "events.parquet", Event)

    def possessions(self, match_id: str) -> list[Possession]:
        return self._read_models(self._match_dir(match_id) / "possessions.parquet", Possession)

    def frames(self, match_id: str) -> list[TrackingFrame]:
        return self._read_models(self._match_dir(match_id) / "frames.parquet", TrackingFrame)

    def query(self, match_id: str, sql: str) -> list[dict[str, object]]:
        """Read-only query over normalized match tables."""
        normalized = sql.strip().lower()
        if not normalized.startswith("select") or ";" in normalized:
            raise ValueError("only one read-only SELECT statement is allowed")
        directory = self._match_dir(match_id)
        connection = duckdb.connect(":memory:")
        try:
            for table in ("events", "possessions", "frames"):
                path = str(directory / f"{table}.parquet").replace("'", "''")
                connection.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{path}')")
            result = connection.execute(sql)
            columns = [column[0] for column in result.description]
            return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
        finally:
            connection.close()

    def save_report(self, report: TacticalReport) -> Path:
        path = self.settings.reports_dir / f"{report.report_id}.json"
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        return path

    def get_report(self, report_id: str) -> TacticalReport:
        path = self.settings.reports_dir / f"{report_id}.json"
        if not path.exists():
            raise KeyError(f"report not found: {report_id}")
        return TacticalReport.model_validate_json(path.read_text(encoding="utf-8"))

    def list_reports(self) -> list[TacticalReport]:
        reports = []
        for path in sorted(self.settings.reports_dir.glob("*.json"), reverse=True):
            reports.append(TacticalReport.model_validate_json(path.read_text(encoding="utf-8")))
        return reports

    def export_report(self, report_id: str, output_format: str, destination: Path | None = None) -> Path:
        from soccer_tactics.reports import render_html, render_markdown

        report = self.get_report(report_id)
        suffix = "html" if output_format == "html" else "md"
        path = destination or self.settings.reports_dir / f"{report_id}.{suffix}"
        content = render_html(report) if suffix == "html" else render_markdown(report)
        path.write_text(content, encoding="utf-8")
        return path
