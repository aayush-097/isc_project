# Reversible Face Privacy for Video

An academic prototype for uploading videos, generating a public face-blurred
copy, and eventually enabling authorized restoration. Phases 1, 2, and 2.5 are
implemented, including the development upload workflow. Production
authentication, encryption, and restoration are not.

## Architecture

- **Frontend:** React, TypeScript, and Vite (`frontend/`).
- **API:** FastAPI (`backend/app/`), with OpenAPI at `/docs`.
- **Metadata:** SQLite (`storage/app.db` by default), initialized without
  deleting existing data and using WAL mode.
- **Case storage:** `storage/cases/`.
- **Development integration:** multipart upload, SQLite job status, processed
  video streaming, and React upload/library/player screens.
- **Planned detector:** a YOLO26n checkpoint fine-tuned on WIDER FACE. The
  general-purpose YOLO26n weights are not a face detector.
- **Video pipeline:** sequential OpenCV frame processing with padded Gaussian
  blur and verified output publication.

`GET /health` and the unauthenticated development video endpoints are
functional. Authentication, ownership checks, case verification, restoration,
and protected public access remain deferred. The video routes are intended
only for local development and must not be exposed to untrusted networks.

## Prerequisites

- Python 3.10 or later (use a version compatible with the installed PyTorch
  build).
- Node.js 22.12 or later and npm.
- For model inference, a compatible PyTorch environment and a face-specific
  YOLO26n checkpoint. No model or dataset is downloaded automatically.

## Configuration

Copy `.env.example` to `.env` and adjust local paths and settings as needed.
The backend reads these settings when it starts:

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Application environment label |
| `DATABASE_PATH` | `storage/app.db` | SQLite database file |
| `STORAGE_PATH` | `storage/cases` | Case-storage root |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Planned frontend origin |
| `SESSION_COOKIE_NAME` | `faceprivacy_session` | Planned session-cookie name |
| `SESSION_COOKIE_SECURE` | `false` | Local-development cookie setting |
| `FACE_MODEL_PATH` | `models/yolo26n_face.pt` | Local face-specific checkpoint |
| `FACE_CONFIDENCE_THRESHOLD` | `0.25` | YOLO detection confidence |
| `FACE_IMAGE_SIZE` | `960` | YOLO inference image size |
| `FACE_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, or a CUDA device index |
| `FACE_BLUR_STRENGTH` | `51` | Odd Gaussian kernel size from 3 to 99 |
| `FACE_BOX_PADDING` | `0.18` | Bounding-box expansion ratio |
| `MAX_VIDEO_UPLOAD_BYTES` | `104857600` | Maximum upload size (100 MiB) |

Relative paths are resolved from the repository root. `.env` is local-only and
ignored by Git. No production secrets are configured or required.

## Backend setup

From the repository root, create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Before installing dependencies, choose a PyTorch and Torchvision build that
matches the host GPU and driver using the official PyTorch installation
selector. The project requirements include minimum versions for these packages;
blindly installing the full requirements file may replace a host-specific
CUDA build. Once the appropriate ML dependencies are in place, install the
remaining requirements and development tools:

```powershell
python -m pip install -r requirements.txt -r requirements-dev.txt
python -m uvicorn backend.app.main:app --reload
```

The API is available at <http://127.0.0.1:8000>, with interactive
documentation at <http://127.0.0.1:8000/docs>. On startup, the app creates the
configured storage directory, missing SQLite tables, and an additive jobs
metrics column if needed; existing rows are not reset.

Check the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`. This indicates API responsiveness only;
it does not indicate that authentication or face detection works.

## Frontend setup

In another terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the FastAPI backend at
`http://127.0.0.1:8000` and removes the `/api` prefix. The frontend calls
`/api/health` and `/api/videos/...`.
Production static serving is left for a later phase.

Build the frontend with:

```powershell
npm run build
```

## Tests and CUDA diagnostic

From the repository root:

```powershell
python -m pytest backend\tests
python scripts\check_cuda.py
```

The CUDA diagnostic reports installed package versions, PyTorch's CUDA
availability and version, and GPU names if available. It does not install
packages, download weights or datasets, run inference, or train a model.
Run all backend and video-processing tests with:

```powershell
python -m pytest backend\tests
```

## Phase 2: face detection and video blurring

The pipeline reads video frames sequentially, calls a reusable detector,
validates and pads returned face boxes, blurs those regions, and writes a
temporary output. It reopens and checks the finished video (dimensions, frame
rate, and frame count) before publishing it. The original face crops are not
saved. OpenCV output does **not** preserve the input audio track.

Configure `FACE_MODEL_PATH` to an existing **face-specific YOLO26n checkpoint
fine-tuned for face detection**. The default path is a proposed location only;
the repository does not include that checkpoint. Missing or non-face model
checkpoints fail clearly. The code never downloads model weights or datasets,
trains a model, or substitutes general-purpose object-detection weights.
`FACE_DEVICE=auto` uses CUDA only when PyTorch reports it available; explicit
CUDA requests fail if CUDA is unavailable. CPU is supported for inference, but
may be slow.

Run the standalone processor from the repository root:

```powershell
python scripts\process_video.py --input PATH_TO_INPUT --output PATH_TO_OUTPUT
```

Optional arguments include `--model`, `--confidence`, `--image-size`,
`--device`, and `--blur-strength`. The CLI accepts explicit input and output
paths. The service function `process_case_video` instead writes to a fixed
`public.mp4` inside the configured storage directory and rejects invalid case
IDs; the development upload endpoint invokes it in a background task.

The JSON metrics report input dimensions, input frame rate and frame count
when available, processed frames, valid detected face instances, frames with
detections, elapsed time, processing FPS, output frame count, output validation
status, and whether CUDA acceleration was selected. If source metadata omits a
valid frame rate, output uses 25 FPS and reports the input rate as `null`.
These statistics describe observed processing, not a privacy guarantee. A
zero-detection result does not prove the video contains no faces or is safe.
Frame-by-frame inference can miss faces; temporal gap filling and tracking are
not implemented.

Automated tests use generated MJPG videos and injected fake detectors; they do
not validate real model accuracy or GPU inference. The current workspace has no
`models/yolo26n_face.pt` checkpoint. At the last environment check, Python was
3.13.2, PyTorch 2.7.0, Torchvision 0.22.0, Ultralytics 8.3.143, and
`torch.cuda.is_available()` was false; the installed ML packages are below the
minimum versions in `requirements.txt`. No ML dependencies or drivers were
changed. Real YOLO inference remains unverified until a compatible environment
and face-specific checkpoint are supplied.

Original face encryption, key management, manifest signing, and restoration
are Phase 3 work and are not implemented here.

## Browser upload workflow (development only)

Run the backend and frontend in separate PowerShell terminals. From the
repository root, activate the existing virtual environment and start FastAPI:

```powershell
.\.venv\Scripts\Activate.ps1
python -m uvicorn backend.app.main:app --reload --host 127.0.0.1 --port 8000
```

In the second terminal:

```powershell
Set-Location frontend
npm run dev
```

Open <http://localhost:5173>, choose **Upload video**, enter a case title,
select a video within the configured size limit, and submit. The browser
reports upload progress, polls processing status, and displays metrics. The
case library at <http://localhost:5173/cases> lists uploaded cases; completed
cases open a player and download link. The browser sends `/api/videos/...`
through Vite's proxy; FastAPI routes themselves are `/videos/...` because the
proxy removes `/api`.

With the current environment, no face-specific checkpoint is present, so an
upload is accepted and then reports a **failed** status with a
`FACE_MODEL_PATH` configuration message. No placeholder video is served as a
successful result. To process videos, provide a compatible local YOLO26n
checkpoint fine-tuned for face detection and a compatible ML environment; the
application does not download models or change dependencies automatically.

Uploads, list/status endpoints, and public videos currently have no
authentication or ownership checks. They store source videos locally and are
not suitable for deployment or access from an untrusted network. The public
video endpoint serves only completed, validated blurred output, never the
uploaded original. Development cases use a reserved database identity with a
non-usable password sentinel solely to satisfy the existing foreign-key
schema; it is not an account or authentication mechanism.

## Implementation status

| Area | Status |
|---|---|
| FastAPI app, health endpoint, OpenAPI contract | Implemented |
| Authentication, sessions, authorization, rate limiting, CSRF | Deferred; endpoints return 501 |
| SQLite schema and repeatable initialization | Implemented; no destructive migration |
| Standalone frame-by-frame face blur pipeline and tests | Implemented with injected test detectors |
| Real YOLO26n face inference | Scaffolded; requires a face-specific checkpoint and compatible ML environment |
| Development upload, job status, case listing, and blurred-video streaming | Implemented; unauthenticated and local-only |
| Authentication, case ownership, secure deployment | Deferred |
| Cryptography, manifests, integrity verification, restoration | Deferred |
| React upload, case library, and playback screens | Implemented for development uploads |
| Login and registration screens | Scaffolded; actions are disabled pending authentication |
| Typed health client and Vite development proxy | Implemented |
| YOLO26n training and dataset downloads | Deferred |

Do not treat remaining API placeholders, the development UI, or face-blur
output as a security guarantee. Further implementation should follow
`PLAN.MD`; this phase does not train a model, download datasets or checkpoints,
or modify the installed CUDA environment.
