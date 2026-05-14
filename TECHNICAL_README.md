# NHA PS3 Doc Forgery Detector - Technical Readme

A practical, CPU-first document forensics system built around explainable, classical computer vision. This readme tells the technical story of how the pipeline, API, and UI evolved into a privacy-first tool that flags tampering without keeping document images.

<div align="left">
  <img alt="Python" height="32" src="https://raw.githubusercontent.com/devicons/devicon/master/icons/python/python-original.svg" />
  <img alt="FastAPI" height="32" src="https://raw.githubusercontent.com/devicons/devicon/master/icons/fastapi/fastapi-original.svg" />
  <img alt="OpenCV" height="32" src="https://raw.githubusercontent.com/devicons/devicon/master/icons/opencv/opencv-original.svg" />
  <img alt="JavaScript" height="32" src="https://raw.githubusercontent.com/devicons/devicon/master/icons/javascript/javascript-original.svg" />
  <img alt="Firebase" height="32" src="https://raw.githubusercontent.com/devicons/devicon/master/icons/firebase/firebase-plain.svg" />
</div>

## The story in one page

We started with a clear constraint: this needs to work on CPU-only machines, at scale, and still be explainable. That meant avoiding heavy deep-learning models and building a classical CV pipeline that can justify every detection with measurable signals. As the project matured, the focus shifted to trust and privacy. The UI became summary-first, history went text-only, and the backend stopped persisting image files altogether. The result is a system that can flag tampering, explain why, and still keep documents ephemeral.

## Tech stack

### Backend
- Python 3.x
- FastAPI for the jobs API
- OpenCV and classic CV routines
- Tesseract OCR (optional; controlled by `OCR_ENABLED`)
- Firebase Admin SDK for auth verification and Firestore summaries

### Frontend
- Static HTML, CSS, vanilla JS
- Firebase Auth + Firestore for users and history
- No client-side image storage

### Data and storage
- Temporary job workspace on disk for pipeline execution
- One-time, in-memory image cache for the rendered preview
- Firestore stores summary-only metadata, never images

## Architecture

```
[Browser]
  | upload
  v
[FastAPI /jobs]
  | run pipeline
  v
[CV + OCR pipeline]
  | results + summary
  v
[Firestore]  (summary only)

In-memory, one-time preview:
CV output image -> _JOB_FILE_BYTES -> /jobs/{id}/files/{file_name} -> client fetch -> delete
```

## Privacy-first behavior (no image storage)

- Uploaded files are stored only in a temporary job directory while the pipeline runs.
- The job directory is deleted after processing.
- Rendered preview images are cached in memory only, served once, then evicted.
- Firestore stores only summary metadata, not images or raw PDFs.
- Cloudinary and any persistent media hosting were removed.

## Core workflow

1) User uploads a file.
2) Backend runs the classical CV pipeline and builds a summary.
3) Results are returned as JSON with per-page detections.
4) The rendered preview is optional and only fetched when the user clicks "Show rendered document." If fetched, it is deleted after that single access.

## API endpoints

- `POST /jobs` - create job, upload a document
- `GET /jobs/{job_id}` - poll status
- `GET /jobs/{job_id}/results` - summary-only results payload
- `GET /jobs/{job_id}/files/{file_name}` - one-time preview bytes

## Local run (developer flow)

Backend:
```
cd .\backend\
$env:DATA_DIR="$PWD\data"
$env:CORS_ORIGINS="http://127.0.0.1:5500,http://localhost:5500"
$env:AUTH_REQUIRED="false"
$env:CLOUDINARY_ENABLED="false"
$env:PIPELINE_PRESET="super_loose"
$env:TESSERACT_CMD="C:\Program Files\Tesseract-OCR\tesseract.exe"
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Frontend:
```
cd .\frontend\
python -m http.server 5500
```

Then open:
```
http://127.0.0.1:5500/app.html
```

## Repository layout (technical view)

- `backend/app/main.py` - FastAPI endpoints, job lifecycle, in-memory preview cache
- `backend/app/pipeline.py` - classical CV pipeline and heuristics
- `frontend/app.js` - UI flow, lazy preview loading, history filters
- `frontend/config.js` - Firebase and API configuration

## Design decisions and tradeoffs

- Classical CV over deep learning: explainable, CPU-ready, and easy to audit.
- Summary-first UI: reviewers need to read results, not store images.
- One-time previews: balanced usability with privacy compliance.
- Text-only history: avoids retaining user documents or thumbnails.

## Notes for maintainers

- Preview bytes are served once. A second fetch returns 404 by design.
- If you add any new storage system, ensure it never persists images or raw PDFs.
- Keep `AUTH_REQUIRED` enabled for production. Local dev can set it to false.
