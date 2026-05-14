# Backend (Render)

This FastAPI service runs the PS3 CV pipeline and exposes job-based APIs.

## Environment variables
- `CORS_ORIGINS`: Comma-separated list of allowed origins (GitHub Pages URL).
- `PIPELINE_PRESET`: `npv_focus` by default.
- `PIPELINE_VERSION`: label shown in UI.
- `MAX_UPLOAD_BYTES`: default 25MB.
- `FINDINGS_MAX_PER_PAGE`: max findings per page (default 5).
- `FINDINGS_MIN_AREA_RATIO`: minimum box area ratio per page (default 0.003).
- `JOB_TTL_SECONDS`: in-memory job retention seconds (default 3600).
- `JOB_EXECUTOR_WORKERS`: number of worker threads.

## Run locally
```
uvicorn app.main:app --reload
```
