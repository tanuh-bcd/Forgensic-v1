import json
import mimetypes
import os
import shutil
import uuid
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .config import (
    AUTH_REQUIRED,
    CORS_ORIGINS,
    DATA_DIR,
    JOB_EXECUTOR_WORKERS,
    MAX_UPLOAD_BYTES,
    OCR_ENABLED,
    PIPELINE_PRESET,
    PIPELINE_VERSION,
)
from .firebase import get_firestore, verify_id_token
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

_executor = ThreadPoolExecutor(max_workers=JOB_EXECUTOR_WORKERS)
_JOB_STATE: Dict[str, Dict[str, Any]] = {}
_JOB_RESULTS: Dict[str, Dict[str, Any]] = {}
_JOB_FILE_BYTES: Dict[str, Dict[str, Dict[str, Any]]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_user_info(authorization: Optional[str]) -> Optional[Dict[str, Any]]:
    if not authorization:
        return None
    if not authorization.lower().startswith("bearer "):
        return None
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        return None
    decoded = verify_id_token(token)
    if not decoded:
        return None
    return {
        "uid": decoded.get("uid"),
        "email": decoded.get("email"),
        "name": decoded.get("name") or decoded.get("displayName"),
    }


def _require_user_info(authorization: Optional[str]) -> Dict[str, Any]:
    info = _get_user_info(authorization)
    if AUTH_REQUIRED and not info:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return info or {"uid": "anonymous"}


def _write_job_state(job_id: str, payload: Dict[str, Any]) -> None:
    _JOB_STATE.setdefault(job_id, {}).update(payload)
    db = get_firestore()
    if db is None:
        return
    db.collection("jobs").document(job_id).set(payload, merge=True)


def _save_upload(upload: UploadFile, dest: Path) -> int:
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="File exceeds 10MB limit")
            f.write(chunk)
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


def _result_to_dict(result: PageAnalysisResult, page: Optional[DocumentPage], image_url: Optional[str]) -> Dict[str, Any]:
    return {
        "page_id": f"{result.file_name}",
        "page_number": result.page_number,
        "file_name": result.file_name,
        "image_url": image_url,
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
        payload_pages.append(_result_to_dict(res, page, image_url))
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
    


def _process_job(job_id: str, user_id: str, file_path: Path, preset: str, ocr_enabled: bool) -> None:
    _write_job_state(job_id, {"status": "processing", "updated_at": _now_iso(), "progress": 0.1})
    job_dir = DATA_DIR / job_id

    try:
        inference_start = perf_counter()
        run_output = run_pipeline(file_path, job_dir, preset=preset, enable_ocr=ocr_enabled)
        inference_seconds = perf_counter() - inference_start
        pages = run_output["pages"]
        results = run_output["results"]
        export_info = run_output["export_info"]
        findings_summary = build_findings_summary(pages, results)

        avg_inference_seconds = None
        if pages:
            avg_inference_seconds = inference_seconds / max(len(pages), 1)

        file_url_map: Dict[str, str] = {}
        for page in pages:
            if not page.image_path:
                continue
            page_path = Path(page.image_path)
            url = _cache_job_file(job_id, page.page_file_name, page_path)
            if url:
                file_url_map[page.page_file_name] = url
            _safe_unlink(page_path)

        payload = _build_results_payload(
            job_id,
            file_path.name,
            pages,
            results,
            export_info,
            file_url_map,
            findings_summary,
            inference_seconds,
            avg_inference_seconds,
        )
        _JOB_RESULTS[job_id] = payload

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
    return {"ok": True, "time": _now_iso()}


@app.post("/jobs", response_model=JobCreateResponse)
async def create_job(
    request: Request,
    file: UploadFile = File(...),
    ocr_enabled: Optional[bool] = Form(None),
) -> JobCreateResponse:
    user = _require_user_info(request.headers.get("authorization"))
    user_id = user.get("uid")
    user_email = user.get("email")
    user_name = user.get("name")

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
            "user_id": user_id,
            "user_email": user_email,
            "user_name": user_name,
            "ocr_enabled": resolved_ocr,
            "created_at": _now_iso(),
            "updated_at": _now_iso(),
            "pipeline_version": PIPELINE_VERSION,
        },
    )

    _executor.submit(_process_job, job_id, user_id, input_path, PIPELINE_PRESET, resolved_ocr)

    return JobCreateResponse(job_id=job_id, status="queued", message="Job accepted")


@app.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: str, request: Request) -> JobStatusResponse:
    _require_user_info(request.headers.get("authorization"))

    state = _JOB_STATE.get(job_id)
    if not state:
        db = get_firestore()
        if db:
            doc = db.collection("jobs").document(job_id).get()
            if doc.exists:
                state = doc.to_dict()
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
async def get_job_results(job_id: str, request: Request) -> JobResultResponse:
    _require_user_info(request.headers.get("authorization"))

    payload = _JOB_RESULTS.get(job_id)
    if not payload:
        db = get_firestore()
        if db:
            doc = db.collection("jobs").document(job_id).get()
            if doc.exists:
                data = doc.to_dict()
                payload = data.get("result")
    if not payload:
        raise HTTPException(status_code=404, detail="Results not ready")

    return JobResultResponse(**payload)


@app.get("/jobs/{job_id}/files/{file_name}")
async def get_job_file(job_id: str, file_name: str, request: Request):
    _require_user_info(request.headers.get("authorization"))

    job_files = _JOB_FILE_BYTES.get(job_id, {})
    entry = job_files.get(file_name)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found")
    data = entry.get("data", b"")
    content_type = entry.get("content_type") or "application/octet-stream"
    job_files.pop(file_name, None)
    if not job_files:
        _JOB_FILE_BYTES.pop(job_id, None)
    return Response(content=data, media_type=content_type)
