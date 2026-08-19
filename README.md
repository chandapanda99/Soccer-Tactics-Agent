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

The data sync command downloads, but never commits, Metrica Sports sample data. Public outputs acknowledge Metrica Sports automatically. Sample Game 1 and 2 use Metrica CSV;
Sample Game 3 uses the FIFA EPTS format.

## Models

Azure Foundry is the default provider. The adapter uses the OpenAI-compatible `/openai/v1/` endpoint and Responses API, preferring an explicit API key and otherwise using
`DefaultAzureCredential`. Set `MODEL_PROVIDER=ollama`
for a local provider. Model credentials never reach the browser.

## Commands

```powershell
uv run soccer-tactics data sync
uv run soccer-tactics data inspect
uv run soccer-tactics analyze sample-game-2 Home
uv run soccer-tactics report export <report-id> --format html
uv run soccer-tactics serve
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

The three anonymized sample matches are a demonstration corpus, not a population-level validation set. Pressure events are tracking-derived proxies, pitch control depends on
reaction and speed assumptions, and control-weighted EPV is a transparent analytical baseline rather than a learned outcome model. Reports expose the active parameter set.
