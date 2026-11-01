# Reversible Face Privacy for Video

An academic prototype for creating a public face-blurred video while preserving
the possibility of authorized restoration. The current repository state is
**Phase 1: foundation and design**. Security and video-processing features are
not yet implemented.

## Architecture

- **Frontend:** React, TypeScript, and Vite (`frontend/`).
- **API:** FastAPI (`backend/app/`), with OpenAPI at `/docs`.
- **Metadata:** SQLite (`storage/app.db` by default), initialized without
  deleting existing data and using WAL mode.
- **Case storage:** `storage/cases/`.
- **Planned detector:** a YOLO26n checkpoint fine-tuned on WIDER FACE. The
  general-purpose YOLO26n weights are not a face detector.

The API currently implements only `GET /health`. Authentication, case and job
operations, video streaming, integrity verification, and restoration are
documented placeholders returning HTTP 501. The frontend shows the planned
screens but does not collect credentials or process videos.

## Prerequisites

- Python 3.10 or later (use a version compatible with the installed PyTorch
  build).
- Node.js 22.12 or later and npm.
- For future model work, an NVIDIA GPU, compatible driver, and CUDA-enabled
  PyTorch build. Phase 1 does not install or replace PyTorch.

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

Relative paths are resolved from the repository root. `.env` is local-only and
ignored by Git. No production secrets are configured or required in Phase 1.

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
configured storage directory and missing SQLite tables; existing tables and
rows are not reset.

Check the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`. This indicates API responsiveness only;
it does not indicate that authentication or processing works.

## Frontend setup

In another terminal:

```powershell
Set-Location frontend
npm ci
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api/*` to the FastAPI backend at
`http://127.0.0.1:8000` and removes the `/api` prefix. The frontend calls
`/api/health`.
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

## Implementation status

| Area | Phase 1 status |
|---|---|
| FastAPI app, health endpoint, OpenAPI contract | Implemented |
| Authentication, sessions, authorization, rate limiting, CSRF | Deferred; endpoints return 501 |
| SQLite schema and repeatable initialization | Implemented; no destructive migration |
| Case upload, processing jobs, public streaming | Deferred; endpoints return 501 |
| Cryptography, manifests, integrity verification, restoration | Deferred |
| React library, upload, login, registration, and case screens | Scaffolded; actions are disabled |
| Typed health client and Vite development proxy | Implemented |
| YOLO26n training, video inference, and CUDA setup changes | Deferred |

Do not treat the Phase 1 API placeholders or UI as security controls. Further
implementation should follow `PLAN.MD`; this phase does not train a model,
download datasets or checkpoints, or modify the installed CUDA environment.
