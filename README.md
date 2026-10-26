# Wind Forecast Portal

This app is a review tool for a UK energy utility day-ahead power buying team. It compares Elexon national wind forecasts with wind actuals for delivery days from 2 January to 1 February 2026 and reports forecast error by day, hour, output level, and forecast horizon.

The application serves a precomputed snapshot. It does not call Elexon while a user is using the app. The Decision view selects the latest forecast available by the configured London cutoff and compares hourly forecasts with hourly actuals derived from half-hourly values.

## Files and directories

- `backend/app/analysis.py` — pure pandas functions for forecast selection, hourly actuals, joins, and error summaries.
- `backend/app/main.py` — FastAPI API and, in the packaged Docker image, static frontend serving.
- `backend/data/` — committed actuals and forecasts parquet snapshots used by production.
- `backend/scripts/` — snapshot ingestion and exploratory/checking scripts.
- `backend/tests/` — pytest tests for analysis and API behavior.
- `frontend/src/` — Vite/React application and plain CSS.
- `api/index.py` — Vercel FastAPI entrypoint.
- `Dockerfile`, `docker-compose.yml`, `.dockerignore` — single-container deployment files.
- `vercel.json`, `requirements.txt` — Vercel deployment configuration.

## How to start the application

### Docker

From the repository root:

```bash
docker compose up --build
```

Open <http://localhost:8000>. The API is available under `/api/`, for example:

```bash
curl http://localhost:8000/api/meta
```

### Local development

Install backend dependencies with uv and frontend dependencies with npm:

```bash
uv sync --project backend
cd frontend && npm ci
```

Start the API from the repository root:

```bash
uv run --project backend uvicorn app.main:app --app-dir backend --reload --port 8000
```

In a second terminal, start Vite:

```bash
cd frontend
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to the backend.

## Live app link

`[Add the deployed application URL here]`

## Key design decisions and assumptions

- For delivery day D, the purchase decision is evaluated using the latest WINDFOR publication at or before D-1 09:00 Europe/London by default. The cutoff can be configured; it is an analysis assumption, not the market gate time.
- Production serves the committed parquet snapshot. `backend/scripts/ingest.py` refreshes it; user requests do not make live Elexon calls.
- Forecast `startTime` is aligned with the hourly actual beginning at the same time. Actual hourly MW is the mean of the two half-hours at T and T+30 minutes.
- Bias is forecast minus actual. Positive bias means the forecast was above actual wind generation.
- The observed bias may be affected by coverage differences between WINDFOR and FUELHH. Those coverage differences have not been compared or quantified here, so the data does not establish the cause of the bias.
- This snapshot covers January 2026 delivery days only and is not a live trading or procurement recommendation.

## Tests

Run the backend tests with:

```bash
uv run --project backend pytest backend/tests
```

The frontend production build can be checked with:

```bash
cd frontend
npm run build
```

## AI tools used

OpenAI Codex (terminal agent) was used for code generation under my direction. I reviewed the generated changes, ran the tests/builds, and checked the rendered application and deployment commands before committing.
