import json
import mimetypes
import shutil
import uuid
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional
from threading import Lock

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .config import (
    CORS_ORIGINS,
    DATA_DIR,
    FINDINGS_MAX_PER_PAGE,
    FINDINGS_MIN_AREA_RATIO,
    JOB_TTL_SECONDS,
    JOB_EXECUTOR_WORKERS,
    MAX_UPLOAD_BYTES,
    OCR_ENABLED,
    PIPELINE_PRESET,
    PIPELINE_VERSION,
)
from .models import JobCreateResponse, JobResultResponse, JobStatusResponse
from .pipeline import DetectedRegion, DocumentPage, PageAnalysisResult, build_findings_summary, run_pipeline

app = FastAPI(title="NHA PS3 Forensics API")

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )

DATA_DIR.mkdir(parents=True, exist_ok=True)

ANALYTICS_FILE = DATA_DIR / "analytics.json"
_ANALYTICS_LOCK = Lock()
_ANALYTICS_STATE: Dict[str, Any] = {}

_executor = ThreadPoolExecutor(max_workers=JOB_EXECUTOR_WORKERS)
_JOB_STATE: Dict[str, Dict[str, Any]] = {}
_JOB_RESULTS: Dict[str, Dict[str, Any]] = {}
_JOB_FILE_BYTES: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _default_analytics_state() -> Dict[str, Any]:
    return {
        "total_docs": 0,
        "total_pages": 0,
        "total_inference_seconds": 0.0,
        "processed_jobs": [],
        "daily": {},
        "last_updated": None,
    }


def _load_analytics_state() -> Dict[str, Any]:
    state = _default_analytics_state()
    if ANALYTICS_FILE.exists():
        try:
            data = json.loads(ANALYTICS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                state.update(data)
        except Exception:
            return state
    state.setdefault("total_docs", 0)
    state.setdefault("total_pages", 0)
    state.setdefault("total_inference_seconds", 0.0)
    state.setdefault("processed_jobs", [])
    state.setdefault("daily", {})
    state.setdefault("last_updated", None)
    return state


def _save_analytics_state(state: Dict[str, Any]) -> None:
    try:
        ANALYTICS_FILE.write_text(json.dumps(state), encoding="utf-8")
    except Exception:
        return


_ANALYTICS_STATE = _load_analytics_state()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        sanitized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(sanitized)
    except ValueError:
        return None


def _cleanup_jobs() -> None:
    if JOB_TTL_SECONDS <= 0:
        return
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=JOB_TTL_SECONDS)
    for job_id, state in list(_JOB_STATE.items()):
        stamp = state.get("updated_at") or state.get("created_at")
        parsed = _parse_iso(stamp)
        if parsed and parsed < cutoff:
            _JOB_STATE.pop(job_id, None)
            _JOB_RESULTS.pop(job_id, None)
            _JOB_FILE_BYTES.pop(job_id, None)
            shutil.rmtree(DATA_DIR / job_id, ignore_errors=True)


def _normalize_granularity(value: Optional[str]) -> str:
    value = (value or "day").lower()
    if value not in {"day", "month", "year"}:
        return "day"
    return value


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _default_range(granularity: str) -> Dict[str, datetime]:
    now = datetime.now(timezone.utc)
    end = now.replace(hour=23, minute=59, second=59, microsecond=999000)
    if granularity == "month":
        start = end.replace(day=1)
        month = start.month - 11
        year = start.year
        while month <= 0:
            month += 12
            year -= 1
        start = start.replace(year=year, month=month)
    elif granularity == "year":
        start = end.replace(month=1, day=1, year=end.year - 4)
    else:
        start = (end - timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
    start = start.replace(hour=0, minute=0, second=0, microsecond=0)
    return {"start": start, "end": end}


def _bucket_key(dt: datetime, granularity: str) -> str:
    if granularity == "month":
        return f"{dt.year}-{dt.month:02d}"
    if granularity == "year":
        return f"{dt.year}"
    return dt.date().isoformat()


def _build_series(granularity: str, start: datetime, end: datetime, daily: Dict[str, Any]) -> Dict[str, Any]:
    buckets = []
    cursor = start.replace(hour=0, minute=0, second=0, microsecond=0)
    if granularity == "month":
        cursor = cursor.replace(day=1)
    if granularity == "year":
        cursor = cursor.replace(month=1, day=1)

    while cursor <= end:
        buckets.append({
            "key": _bucket_key(cursor, granularity),
            "date": cursor.date().isoformat(),
            "docs": 0,
            "pages": 0,
        })
        if granularity == "month":
            month = cursor.month + 1
            year = cursor.year
            if month > 12:
                month = 1
                year += 1
            cursor = cursor.replace(year=year, month=month, day=1)
        elif granularity == "year":
            cursor = cursor.replace(year=cursor.year + 1, month=1, day=1)
        else:
            cursor = cursor + timedelta(days=1)

    bucket_map = {bucket["key"]: bucket for bucket in buckets}
    for day_key, stats in daily.items():
        parsed = _parse_iso(day_key)
        if not parsed:
            continue
        parsed = _to_utc(parsed)
        if parsed < start or parsed > end:
            continue
        key = _bucket_key(parsed, granularity)
        bucket = bucket_map.get(key)
        if not bucket:
            continue
        bucket["docs"] += int(stats.get("docs", 0))
        bucket["pages"] += int(stats.get("pages", 0))
    return {"series": buckets}


def _record_analytics(job_id: str, pages_count: int, inference_seconds: Optional[float], created_at: Optional[str]) -> None:
    stamp = _parse_iso(created_at) or datetime.now(timezone.utc)
    stamp = _to_utc(stamp)
    with _ANALYTICS_LOCK:
        state = _ANALYTICS_STATE
        processed = state.setdefault("processed_jobs", [])
        if job_id in processed:
            return
        processed.append(job_id)

        state["total_docs"] = int(state.get("total_docs", 0)) + 1
        state["total_pages"] = int(state.get("total_pages", 0)) + int(pages_count or 0)
        state["total_inference_seconds"] = float(state.get("total_inference_seconds", 0.0)) + float(inference_seconds or 0.0)
        state["last_updated"] = _now_iso()

        day_key = stamp.date().isoformat()
        daily = state.setdefault("daily", {})
        entry = daily.setdefault(day_key, {"docs": 0, "pages": 0, "inference_seconds": 0.0})
        entry["docs"] = int(entry.get("docs", 0)) + 1
        entry["pages"] = int(entry.get("pages", 0)) + int(pages_count or 0)
        entry["inference_seconds"] = float(entry.get("inference_seconds", 0.0)) + float(inference_seconds or 0.0)

        _save_analytics_state(state)


def _write_job_state(job_id: str, payload: Dict[str, Any]) -> None:
    _JOB_STATE.setdefault(job_id, {}).update(payload)


def _save_upload(upload: UploadFile, dest: Path) -> int:
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dest.open("wb") as f:
            while True:
                chunk = upload.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="File exceeds 25MB limit")
                f.write(chunk)
    except HTTPException:
        try:
            dest.unlink()
        except FileNotFoundError:
            pass
        raise
    except Exception:
        try:
            dest.unlink()
        except FileNotFoundError:
            pass
        raise
    return size


def _allowed_suffix(name: str) -> bool:
    suffix = Path(name).suffix.lower()
    return suffix in {".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}


def _region_to_dict(region: DetectedRegion) -> Dict[str, Any]:
    return {
        "x": region.x,
        "y": region.y,
        "w": region.w,
        "h": region.h,
        "category_id": region.category_id,
        "type": region.type,
        "stretch_factor": region.stretch_factor,
        "header_source": region.header_source,
        "body_source": region.body_source,
    }


def _result_to_dict(
    result: PageAnalysisResult,
    page: Optional[DocumentPage],
    image_url: Optional[str],
    preview_url: Optional[str],
) -> Dict[str, Any]:
    return {
        "page_id": f"{result.file_name}",
        "page_number": result.page_number,
        "file_name": result.file_name,
        "image_url": image_url,
        "preview_url": preview_url,
        "image_width": page.image_width if page else None,
        "image_height": page.image_height if page else None,
        "categories": result.predicted_categories,
        "regions": [_region_to_dict(r) for r in result.detected_regions],
        "notes": result.notes,
    }


def _build_results_payload(
    job_id: str,
    file_name: str,
    pages: list,
    results: list,
    export_info: Dict[str, Any],
    file_url_map: Dict[str, str],
    preview_url_map: Dict[str, str],
    findings_summary: Optional[Dict[str, Any]] = None,
    inference_seconds: Optional[float] = None,
    avg_inference_seconds: Optional[float] = None,
) -> Dict[str, Any]:
    page_map = {p.page_file_name: p for p in pages}
    payload_pages = []
    summary: Dict[str, int] = {}
    for res in results:
        page = page_map.get(res.file_name)
        image_url = file_url_map.get(res.file_name)
        preview_url = preview_url_map.get(res.file_name)
        payload_pages.append(_result_to_dict(res, page, image_url, preview_url))
        for cat in res.predicted_categories:
            summary[cat] = summary.get(cat, 0) + 1

    export_urls = {
        "json": file_url_map.get("submission.json"),
        "excel": file_url_map.get("submission_preview.xlsx"),
        "yaml": [file_url_map.get(Path(p).name) for p in export_info.get("yaml_paths", []) if file_url_map.get(Path(p).name)],
    }
    if not any([export_urls.get("json"), export_urls.get("excel"), export_urls.get("yaml")]):
        export_urls = {}

    return {
        "job_id": job_id,
        "status": "complete",
        "file_name": file_name,
        "pipeline_version": PIPELINE_VERSION,
        "pages": payload_pages,
        "category_summary": summary,
        "export_urls": export_urls,
        "findings_summary": findings_summary,
        "inference_seconds": inference_seconds,
        "avg_inference_seconds": avg_inference_seconds,
        "created_at": _JOB_STATE.get(job_id, {}).get("created_at"),
        "updated_at": _JOB_STATE.get(job_id, {}).get("updated_at"),
    }


def _safe_unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except Exception:
        return


def _cache_job_file(job_id: str, name: str, path: Path) -> Optional[str]:
    if not path.exists():
        return None
    content_type, _ = mimetypes.guess_type(str(path))
    try:
        data = path.read_bytes()
    except Exception:
        return None
    job_files = _JOB_FILE_BYTES.setdefault(job_id, {})
    job_files[name] = {
        "content_type": content_type or "application/octet-stream",
        "data": data,
    }
    return f"/jobs/{job_id}/files/{name}"
    


def _process_job(job_id: str, file_path: Path, preset: str, ocr_enabled: bool) -> None:
    _write_job_state(job_id, {"status": "processing", "updated_at": _now_iso(), "progress": 0.1})
    job_dir = DATA_DIR / job_id

    try:
        inference_start = perf_counter()
        run_output = run_pipeline(file_path, job_dir, preset=preset, enable_ocr=ocr_enabled)
        inference_seconds = perf_counter() - inference_start
        pages = run_output["pages"]
        results = run_output["results"]
        export_info = run_output["export_info"]
        findings_summary = build_findings_summary(
            pages,
            results,
            max_per_page=FINDINGS_MAX_PER_PAGE,
            min_area_ratio=FINDINGS_MIN_AREA_RATIO,
        )

        avg_inference_seconds = None
        if pages:
            avg_inference_seconds = inference_seconds / max(len(pages), 1)

        file_url_map: Dict[str, str] = {}
        preview_url_map: Dict[str, str] = {}
        for page in pages:
            page_path = None
            if page.image_path:
                page_path = Path(page.image_path)
            elif page.original_path:
                page_path = Path(page.original_path)

            if page_path and page_path.exists():
                url = _cache_job_file(job_id, page.page_file_name, page_path)
                if url:
                    file_url_map[page.page_file_name] = url
                _safe_unlink(page_path)

            preview_path = Path(page.preview_path) if page.preview_path else None
            if preview_path and preview_path.exists():
                if not page_path or preview_path.resolve() != page_path.resolve():
                    preview_url = _cache_job_file(job_id, preview_path.name, preview_path)
                    if preview_url:
                        preview_url_map[page.page_file_name] = preview_url
                    _safe_unlink(preview_path)

        payload = _build_results_payload(
            job_id,
            file_path.name,
            pages,
            results,
            export_info,
            file_url_map,
            preview_url_map,
            findings_summary,
            inference_seconds,
            avg_inference_seconds,
        )
        _JOB_RESULTS[job_id] = payload

        _record_analytics(
            job_id,
            len(pages) if pages else 0,
            inference_seconds,
            _JOB_STATE.get(job_id, {}).get("created_at"),
        )

        summary_payload = {
            "job_id": job_id,
            "status": "complete",
            "file_name": file_path.name,
            "pipeline_version": PIPELINE_VERSION,
            "pages": [],
            "category_summary": payload.get("category_summary", {}),
            "export_urls": {},
            "findings_summary": findings_summary,
            "inference_seconds": inference_seconds,
            "avg_inference_seconds": avg_inference_seconds,
            "created_at": _JOB_STATE.get(job_id, {}).get("created_at"),
            "updated_at": _now_iso(),
        }

        _write_job_state(
            job_id,
            {
                "status": "complete",
                "updated_at": _now_iso(),
                "progress": 1.0,
                "inference_seconds": inference_seconds,
                "avg_inference_seconds": avg_inference_seconds,
                "summary_text": (findings_summary or {}).get("summary_text"),
                "category_summary": payload.get("category_summary", {}),
                "result": summary_payload,
            },
        )

    except Exception as exc:
        _write_job_state(job_id, {"status": "error", "updated_at": _now_iso(), "message": str(exc)})
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)


@app.get("/health")
async def health() -> Dict[str, Any]:
    _cleanup_jobs()
    return {"ok": True, "time": _now_iso()}


@app.get("/analytics")
async def get_analytics(
    granularity: str = "day",
    from_: Optional[str] = Query(None, alias="from"),
    to: Optional[str] = Query(None, alias="to"),
) -> Dict[str, Any]:
    _cleanup_jobs()
    granularity = _normalize_granularity(granularity)
    defaults = _default_range(granularity)
    with _ANALYTICS_LOCK:
        state = _ANALYTICS_STATE
        total_docs = int(state.get("total_docs", 0))
        total_pages = int(state.get("total_pages", 0))
        total_seconds = float(state.get("total_inference_seconds", 0.0))
        last_updated = state.get("last_updated")
        daily = dict(state.get("daily", {}))

    start = _parse_iso(from_) or defaults["start"]
    end = _parse_iso(to) or defaults["end"]

    start = _to_utc(start)
    end = _to_utc(end)
    if start > end:
        start, end = end, start

    series_payload = _build_series(granularity, start, end, daily)
    series = series_payload.get("series", [])
    range_docs = sum(bucket.get("docs", 0) for bucket in series)
    range_pages = sum(bucket.get("pages", 0) for bucket in series)
    avg_seconds = total_seconds / total_pages if total_pages else None

    return {
        "granularity": granularity,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "total_docs": total_docs,
        "total_pages": total_pages,
        "avg_seconds_per_page": avg_seconds,
        "range_docs": range_docs,
        "range_pages": range_pages,
        "last_updated": last_updated,
        "series": series,
    }


@app.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    file: UploadFile = File(...),
    ocr_enabled: Optional[bool] = Form(None),
) -> JobCreateResponse:
    _cleanup_jobs()
    if not file.filename or not _allowed_suffix(file.filename):
        raise HTTPException(status_code=400, detail="Unsupported file type")

    job_id = uuid.uuid4().hex
    job_dir = DATA_DIR / job_id
    input_path = job_dir / "input" / file.filename
    size = _save_upload(file, input_path)

    resolved_ocr = OCR_ENABLED if ocr_enabled is None else bool(ocr_enabled)

    _write_job_state(
        job_id,
        {
            "job_id": job_id,
            "status": "queued",
            "progress": 0.0,
            "file_name": file.filename,
            "file_size": size,
            "ocr_enabled": resolved_ocr,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "pipeline_version": PIPELINE_VERSION,
        },
    )

    _executor.submit(_process_job, job_id, input_path, PIPELINE_PRESET, resolved_ocr)

    return JobCreateResponse(job_id=job_id, status="queued", message="Job accepted")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str) -> JobStatusResponse:
    _cleanup_jobs()
    state = _JOB_STATE.get(job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job_id,
        status=state.get("status", "unknown"),
        progress=state.get("progress"),
        message=state.get("message"),
        created_at=state.get("created_at"),
        updated_at=state.get("updated_at"),
    )


@app.get("/jobs/{job_id}/results", response_model=JobResultResponse)
async def get_job_results(job_id: str) -> JobResultResponse:
    _cleanup_jobs()
    payload = _JOB_RESULTS.get(job_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Results not ready")

    return JobResultResponse(**payload)


@app.get("/jobs/{job_id}/files/{file_name}")
async def get_job_file(job_id: str, file_name: str):
    _cleanup_jobs()
    job_files = _JOB_FILE_BYTES.get(job_id, {})
    entry = job_files.get(file_name)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    data = entry.get("data", b"")
    content_type = entry.get("content_type") or "application/octet-stream"
    return Response(content=data, media_type=content_type)
