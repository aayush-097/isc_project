# Reversible Face Privacy for Video

An academic prototype for uploading videos, generating an authenticated
detected-person-blurred copy, and protecting original videos with per-video
passkeys and encryption. Production deployment hardening remains incomplete.

## Architecture

- **Frontend:** React, TypeScript, and Vite (`frontend/`).
- **API:** FastAPI (`backend/app/`), with OpenAPI at `/docs`.
- **Metadata:** SQLite (`storage/app.db` by default), initialized without
  deleting existing data and using WAL mode.
- **Case storage:** `storage/cases/`.
- **Video workflow:** authenticated uploads and library, owner-only retry/delete,
  validated blurred streaming, and passkey-protected original streaming.
- **Original-video protection:** AES-256-GCM chunk encryption at rest, per-video
  random data keys wrapped using Argon2id-derived passkey keys, and short-lived
  user/video/session-bound unlock grants.
- **Detector:** local `models/yolo26n.pt`, configured to detect the COCO
  `person` class and blur detected whole-person boxes. This is not face-only
  detection; people can be missed.
- **Video pipeline:** sequential OpenCV frame processing with padded Gaussian
  blur and verified output publication.

`GET /health`, account registration/login/logout, current-session lookup, and
the video processing and access workflow are functional. Authentication sessions
are server-side and revocable, with Argon2 password hashes and CSRF-protected
state-changing requests. Case verification and restoration remain deferred.
Face-crop restoration remains deferred; original video access uses the
per-video passkey workflow described below. The prototype is not a production
deployment; configure HTTPS, secure cookies, and appropriate operational
controls before exposing it beyond local use.

## Prerequisites

- Python 3.10 or later (use a version compatible with the installed PyTorch
  build).
- Node.js 22.12 or later and npm.
- System FFmpeg on `PATH`, built with the `libx264` and AAC encoders.
  Media tests also require `ffprobe`. These binaries are not installed by pip;
  check availability with `ffmpeg -version` and `ffprobe -version`.
- For model inference, a compatible PyTorch environment and the local YOLO
  checkpoint. No model or dataset is downloaded automatically.

## Configuration

Copy `.env.example` to `.env` and adjust local paths and settings as needed.
The backend reads these settings when it starts:

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | Application environment label |
| `DATABASE_PATH` | `storage/app.db` | SQLite database file |
| `STORAGE_PATH` | `storage/cases` | Case-storage root |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | Planned frontend origin |
| `SESSION_COOKIE_NAME` | `faceprivacy_session` | HttpOnly session-cookie name |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` when serving over HTTPS |
| `SESSION_TTL_SECONDS` | `43200` | Session lifetime (12 hours by default) |
| `FACE_MODEL_PATH` | `models/yolo26n.pt` | Local YOLO checkpoint |
| `FACE_DETECTION_CLASS` | `person` | `person` blurs person boxes; `face` requires a face-specific checkpoint |
| `FACE_CONFIDENCE_THRESHOLD` | `0.05` | YOLO detection confidence (low threshold for broader person coverage) |
| `FACE_IMAGE_SIZE` | `640` | YOLO inference image size used by the supplied checkpoint |
| `FACE_DEVICE` | `auto` | `auto`, `cpu`, `cuda`, or a CUDA device index |
| `FACE_BLUR_STRENGTH` | `99` | Odd Gaussian kernel size from 3 to 99 |
| `FACE_BOX_PADDING` | `0.18` | Bounding-box expansion ratio |
| `MAX_VIDEO_UPLOAD_BYTES` | `524288000` | Maximum upload size (500 MiB; UI labels this 500 MB) |

Relative paths are resolved from the repository root. `.env` is local-only and
ignored by Git. No production secrets are configured or required.
Existing `.env` overrides remain in effect: update the upload limit and blur
strength there if they still select the previous 100 MiB / 51-kernel defaults.

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
configured storage directory, missing SQLite tables, and additive jobs/video
metadata columns if needed; existing rows are not reset or reassigned.

Check the health endpoint:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response: `{"status":"ok"}`. This indicates API responsiveness only.

## Accounts

Open `/register` to create an account or `/login` to sign in. Usernames are
normalized to lowercase and accept 3–64 letters, numbers, dots, underscores,
and hyphens. Passwords must be at least 12 characters. Passwords are stored
using Argon2id hashes. Successful registration and login create a 12-hour
server-side session, returned as an HttpOnly, SameSite=Strict cookie. The raw
session token is not stored in SQLite; only its SHA-256 hash is stored.
`POST /auth/logout` revokes the current session and requires the per-session
CSRF token. Five failed password attempts lock that account for 15 minutes.

Set `SESSION_COOKIE_SECURE=true` when the app is served over HTTPS. The default
development cookie is not marked Secure so it works on localhost. Login and
registration enforce the configured `FRONTEND_ORIGIN` when the browser sends
an Origin header.

Video uploads require a signed-in account and CSRF token. Ownership is assigned
from the authenticated session and controls retry/delete actions. Any signed-in
user can browse video metadata and validated blurred output. To access an
original, a signed-in user must enter that video's passkey; successful unlocks
create a five-minute grant bound to the video, user, and current session. Grants
are revoked at logout, passkey attempts are limited to five failures per
video/user every 15 minutes, and original responses are non-cacheable and
support authenticated byte ranges. Originals are unavailable while processing.
A lost passkey cannot be recovered.

Uploads are encrypted at rest using independent authenticated AES-256-GCM
chunks. Each video has a random data-encryption key wrapped by a key derived
from its passkey with Argon2id. The original is decrypted only into a temporary
file while processing and that file is removed after the job. The backend does
not mount case storage as static files. Blurred output is stored separately and
served only after output validation.

Database migrations add video metadata, grant, and rate-limit tables without
deleting existing data or guessing legacy ownership. Legacy cases remain
visible to signed-in users and previously validated blurred output can still be
served, but legacy originals without encryption metadata are never served.
New files are stored under `storage/cases/<case-id>/encrypted/` and
`storage/cases/<case-id>/processed/`.

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
validates and pads returned person boxes in the default configuration, applies a 99-kernel Gaussian blur by
default, and writes a temporary MJPG video. FFmpeg combines only that blurred
video with the source's optional audio tracks. MP4/M4V/MOV outputs use H.264
with limited-range `yuv420p`, AAC audio, and faststart metadata for browser
playback and seeking. CLI AVI outputs retain MJPG video and use PCM audio.
Silent sources remain silent; shorter audio does not truncate video.

The final encoded video is reopened and checked for dimensions, frame rate,
and exact processed frame count before atomic publication. Encoding failures
never publish partial output. Original face crops are not saved. Audio content
is preserved, not anonymized; voices can still identify people.

The current default uses `models/yolo26n.pt` with
`FACE_DETECTION_CLASS=person`. The detector selects the person class and uses
each detected person box as the blur region. This is broader than face blur but
is not a guarantee: a missed person detection leaves that person's face
unblurred. The notebook-trained `yolo26n_widerface_best.pt` can instead be used
with `FACE_DETECTION_CLASS=face` for face-box blur. Set `FACE_MODEL_PATH` to the
local checkpoint and restart the backend to apply changes. The backend exposes
`GET /health/face-model` and the upload page shows the configured target class.
Missing weights block new uploads; failed cases can be retried after the
checkpoint is available.
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
`processed/public.mp4` inside the configured case directory and rejects
invalid case IDs; the upload endpoint invokes it in a background task.

The JSON metrics report input dimensions, input frame rate and the
container-reported frame-count estimate when available, processed frames, valid
detected face instances, frames with detections, elapsed time, processing FPS,
output frame count, output validation status, and whether CUDA was selected.
The input estimate is used for progress reporting only: it can overcount or
undercount and is not a completeness requirement. Publication requires the
decoded output count to exactly match the frames actually decoded and processed
from the input; missing output frames still fail validation. No frames are
added or dropped to match metadata. OpenCV read failure ends input decoding,
so this check does not independently certify that the source is corruption-free.
If source metadata omits a valid frame rate, output uses 25 FPS and reports the
input rate as `null`.
These statistics describe observed processing, not a privacy guarantee. A
zero-detection result does not prove the video contains no faces or is safe.
Frame-by-frame inference can miss faces; temporal gap filling and tracking are
not implemented.

Automated tests use generated MJPG videos and injected fake detectors; they do
not measure real model accuracy. The notebook records a WIDER FACE validation
result and writes its trained checkpoint to the output path above. Activate a
Python environment containing the declared dependencies before starting the
backend or CLI; the default shell's Python may not have them. A small
integration check does not establish face coverage, accuracy, or representative
throughput.

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

With the configured checkpoint present and a compatible Python environment
active, uploads use the configured detector through the same pipeline as the
CLI. In the default person mode, the whole detected person boxes are blurred,
not face-only crops. The upload page checks checkpoint availability before
accepting a video, and the case library can retry a failed case after installing
the checkpoint. The application does not download models or change dependencies
automatically.

Previously generated videos are not rewritten automatically. Re-upload the
original after restarting the backend to get stronger blur, retained audio,
and browser-compatible encoding. Older `mp4v` files can download successfully
while failing in the browser player; the `.mp4` extension alone does not
guarantee a supported video codec.

Uploads, private list/status endpoints, retries, original-video streaming, and
deletion require an authenticated owner session. Other viewers can access only
completed, validated blurred output. Older case records previously attached to
the reserved `__development_uploads__` identity are deliberately not assigned
to a real account; their originals are inaccessible through the API. The
reserved identity is not a login or authentication mechanism.

## Implementation status

| Area | Status |
|---|---|
| FastAPI app, health endpoint, OpenAPI contract | Implemented |
| Authentication, password hashing, revocable sessions, login lockout, CSRF protection | Implemented |
| SQLite schema and repeatable initialization | Implemented; additive auth and video metadata migrations |
| Standalone frame-by-frame face blur pipeline and tests | Implemented with injected test detectors |
| YOLO26n person-box blur | Integrated with the local `models/yolo26n.pt`; whole detected people are blurred |
| Video upload, owner-only library/status/original/retry/delete, blurred sharing | Implemented |
| Production deployment hardening, cryptography, restoration | Deferred |
| Manifests, integrity verification, restoration | Deferred |
| React upload, private library, and owner/shared playback screens | Implemented |
| Login and registration screens | Functional; login state shown in navigation |
| Face-model readiness status and Vite development proxy | Implemented |
| YOLO26n training and dataset downloads | Training notebook supplied; runtime does not train or download |

Do not treat remaining API placeholders, the development UI, or face-blur
output as a security guarantee. Further implementation should follow
`PLAN.MD`; this phase does not train a model, download datasets or checkpoints,
or modify the installed CUDA environment.
