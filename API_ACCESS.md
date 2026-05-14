# API Access - Forgensic

This document explains how to integrate with the Forgensic API. The API is designed for privacy-first document forensics and returns summary-only results. Rendered previews are optional and served once.

## Base URL

Set your base URL to the backend host you are running:

```
http://127.0.0.1:8000
```

## Authentication

- If `AUTH_REQUIRED=true`, send a Firebase ID token in the `Authorization` header.
- For local demos you can set `AUTH_REQUIRED=false` to disable auth.

```
Authorization: Bearer YOUR_FIREBASE_ID_TOKEN
```

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| POST | /jobs | Create a job and upload a document (multipart) |
| GET | /jobs/{job_id} | Poll job status and progress |
| GET | /jobs/{job_id}/results | Fetch summary-only results payload |
| GET | /jobs/{job_id}/files/{file_name} | One-time preview bytes for a rendered page image |
| GET | /health | Service health check |

## Quick start (curl)

### 1) Upload a document

```
curl -X POST "http://127.0.0.1:8000/jobs" \
  -H "Authorization: Bearer YOUR_FIREBASE_ID_TOKEN" \
  -F "file=@/path/to/document.pdf" \
  -F "ocr_enabled=true"
```

### 2) Poll status

```
curl -X GET "http://127.0.0.1:8000/jobs/JOB_ID" \
  -H "Authorization: Bearer YOUR_FIREBASE_ID_TOKEN"
```

### 3) Fetch results

```
curl -X GET "http://127.0.0.1:8000/jobs/JOB_ID/results" \
  -H "Authorization: Bearer YOUR_FIREBASE_ID_TOKEN"
```

### 4) One-time preview download

```
curl -L "http://127.0.0.1:8000/jobs/JOB_ID/files/PAGE_001.png" \
  -H "Authorization: Bearer YOUR_FIREBASE_ID_TOKEN" \
  -o preview.png
```

A second request to the same preview URL returns 404 by design.

## Response examples

### Job status

```
{
  "job_id": "abc123",
  "status": "processing",
  "progress": 0.42,
  "created_at": "2026-05-14T10:04:12Z",
  "updated_at": "2026-05-14T10:04:45Z"
}
```

### Results summary

```
{
  "job_id": "abc123",
  "status": "complete",
  "file_name": "report.pdf",
  "category_summary": {"C1": 2, "C3": 1},
  "findings_summary": {
    "summary_text": "Page 1: Added content near \"Hospital Seal\" appears altered.",
    "findings": [
      {
        "page": 1,
        "category_id": "C3",
        "category_label": "Added content",
        "snippet": "Hospital Seal",
        "location": "top-right",
        "summary": "Page 1: Added content near \"Hospital Seal\" appears altered."
      }
    ]
  },
  "pages": [
    {"page_number": 1, "image_url": "/jobs/abc123/files/page_001.png"}
  ]
}
```

### Findings summary notes

- `findings_summary.summary_text` is a human-readable, page-by-page synopsis.
- If OCR is disabled or unavailable, `findings_summary` may be null or have an empty `summary_text`.

## Privacy guarantees

- Uploaded files are stored only during processing.
- Job directories are deleted after processing completes.
- Rendered previews are cached in memory and served once.
- Firestore stores summary-only metadata (no images or PDFs).

## OpenAPI docs

- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`
