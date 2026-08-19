# Soccer Tactics Agent

A local-first tactical analyst for synchronized soccer event and tracking data. Deterministic Python analytics produce the evidence; a LangChain Deep Agent turns that evidence
into cited reports and lets you challenge each claim.

## What it analyzes

- Passing networks and progression
- Defensive compactness
- Inferred pressing patterns
- Probabilistic pitch control
- Space creation
- Transition opportunities

Every claim links to possessions, events, and tracking frames. The agent cannot execute arbitrary code or make an uncited numerical claim. If no model is configured, the
application produces a deterministic evidence report.

## Development

Requirements: Python 3.14, [uv](https://docs.astral.sh/uv/), and Node.js 20+.

On Windows, the project script installs dependencies, builds the production frontend, and starts the complete app:

```powershell
.\scripts\project.ps1
```

Open `http://127.0.0.1:8766`. Additional modes and options:

```powershell
.\scripts\project.ps1 build
.\scripts\project.ps1 test
.\scripts\project.ps1 run -ListenAddress 0.0.0.0 -Port 9000
.\scripts\project.ps1 run -SkipInstall
```

The script uses `uv` for Python syncing, builds, and command execution. It uses npm only for the Svelte/TypeScript frontend.

For a split backend/frontend development setup:

```powershell
Copy-Item .env.example .env
uv sync --extra test
uv run soccer-tactics data sync
uv run soccer-tactics serve
```

In a second terminal:

```powershell
Set-Location frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. The backend listens on `http://127.0.0.1:8766`.

The data sync commands download, but never commit, third-party data. Public outputs carry the matching source attribution. Sample Game 1 and 2 use Metrica CSV; Sample Game 3
uses FIFA EPTS. SkillCorner supplies ten identified 2024/25 A-League matches with 10 Hz broadcast tracking, dynamic events, and provider phases.

## Models

Azure Foundry is the default provider. The adapter uses the OpenAI-compatible `/openai/v1/` endpoint and Responses API, preferring an explicit API key and otherwise using
`DefaultAzureCredential`. Set `MODEL_PROVIDER=ollama`
for a local provider. Model credentials never reach the browser.

## Commands

```powershell
uv run soccer-tactics data sync
uv run soccer-tactics data skillcorner catalog
uv run soccer-tactics data skillcorner sync 1886347
uv run soccer-tactics data inspect
uv run soccer-tactics analyze sample-game-2 Home
uv run soccer-tactics report export <report-id> --format html
uv run soccer-tactics serve
```

Raw Metrica files remain at their original 25 Hz. The default processed analytical cache is 5 Hz; choose another rate or
optionally create a second full-rate Parquet cache when an experiment needs every frame:

```powershell
uv run soccer-tactics data sync --sample-rate-hz 10
uv run soccer-tactics data sync --retain-full-tracking
```

Processed match metadata records the ingestion version, analytical sample rate, full-rate cache choice, source checksum,
and possession derivation method. Normalized events retain receiver/end timing fields and a JSON copy of source attributes.

SkillCorner matches are downloaded selectively because each tracking file can exceed 80 MB. The application preserves the
provider's attribution and records caveats about broadcast extrapolation and the published player-identity accuracy. For example:

```powershell
uv run soccer-tactics data skillcorner catalog
uv run soccer-tactics data skillcorner sync 1886347 --sample-rate-hz 5
uv run soccer-tactics analyze skillcorner-1886347 Home
```

## Verification

```powershell
uv run --extra test pytest
uv run ruff check .
Set-Location frontend
npm run check
npm run test
npm run build
```

## Methodological limits

The three anonymized Metrica matches and ten SkillCorner matches are demonstration corpora, not population-level validation sets. SkillCorner tracking is inferred from broadcast
video and contains extrapolated positions; the provider reports approximately 97% player-identity accuracy. Pressure events are tracking-derived proxies, pitch control depends
on reaction and speed assumptions, and control-weighted EPV is a transparent analytical baseline rather than a learned outcome model. Reports expose the active parameter set.
