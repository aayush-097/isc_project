# Updated Execution Plan: Reversible Face Privacy for Video

**Stack:** FastAPI + React, SQLite, YOLO26n fine-tuned on WIDER FACE on a CUDA laptop. **Timeline:** 6 weeks, team of 3-4.

## What changed

- **Audit log removed entirely.** The Isolation Forest anomaly detection and the admin alerts were built on top of that log, so they go too. The AI domain still has real weight, because you now train and evaluate your own YOLO26 face detector. The security domain is covered by authentication, access control, encryption-enforced ownership, and tamper detection.
- **Access model is owner-only.** Any logged-in user can upload, and anyone logged in can watch any blurred video. Only the uploader can restore the faces of their own video. The admin role and the revoke feature are gone.
- **Face detector is YOLO26n, fine-tuned on WIDER FACE.**
- **SQLite stays.**

## 1. Face detection model: YOLO26n

**Decision: use YOLO26n fine-tuned on WIDER FACE.** YOLO26s training and the n-vs-s comparison are not part of the project scope.

The official `yolo26n.pt` weights are general-purpose detectors, not face detectors. The project must use a WIDER FACE fine-tuned YOLO26n checkpoint for face inference.

- **Training:** when implementation is authorized, convert WIDER FACE to YOLO format (one class, about 12.9k train and 3.2k val images) and fine-tune YOLO26n:

```bash
pip install -r requirements.txt
yolo detect train model=yolo26n.pt data=widerface.yaml imgsz=640 epochs=50 batch=4 device=0
```

  Adjust `batch` to the available VRAM. Repository setup does not include downloading weights or datasets, running inference, or starting training.
- **Inference:** use a low confidence threshold and a bigger image size for small faces, since a missed face is a privacy leak:

```python
res = model.predict(frame, conf=0.25, imgsz=960, device=0, half=True, verbose=False)[0]
boxes = res.boxes.xyxy.cpu().numpy().astype(int)
```

- **Optional speedup:** export to TensorRT (`model.export(format="engine", half=True)`) if the demo needs more fps.
- **Report evaluation:** evaluate the fine-tuned YOLO26n on WIDER FACE val (mAP50) and on about 100 frames you label from your own test videos (recall, precision, fps on your GPU).
- **Setup check:** install the CUDA build of PyTorch and confirm `torch.cuda.is_available()` before anything else.
- **Licensing note for the report:** Ultralytics YOLO26 is AGPL-3.0, and WIDER FACE is listed as non-commercial research data. Both are fine for an academic project, but mention them.

## 2. Architecture

```
┌──────────── React (Vite) ────────────┐        ┌────────────── FastAPI ──────────────┐
│ Login / Register                     │◄─HTTPS─►│ Cookie sessions, CSRF, rate limits  │
│ Library: all cases ("Yours" badge)   │  JSON  │ Ownership check on every restore    │
│ Case page: public video, and for the│  + MJPEG│ Background job: protect pipeline    │
│   owner a "Restore faces" flow       │        │ core/ crypto/ security/ modules     │
│ Upload page with progress            │        └───────────────┬─────────────────────┘
└──────────────────────────────────────┘                        │
                                                     SQLite (app.db) + case folders
                                                                │
                                          YOLO26 on CUDA ── detect → blur / encrypt
```

**Case folder:**

```
case_001/
├── public.mp4        # blurred video, visible to every logged-in user
├── faces.db          # encrypted crops: frame, x, y, w, h, nonce, ct
├── keys.json         # the DEK wrapped with the OWNER's RSA public key only
├── manifest.json     # SHA-256 of the files above
└── manifest.sig      # signature over the manifest
```

## 3. Access control: two layers

1. **API layer:** a `require_owner(case_id)` dependency compares the session user to `cases.owner_id`. A non-owner gets 403.
2. **Crypto layer:** the case's AES key is wrapped only for the owner. The owner's private key is encrypted under their password. So even if someone bypasses the API or copies the whole database, they only get ciphertext.

**Consequence to state in your report:** there is no password recovery for restoring faces. If an owner forgets their password, their faces can't be restored, and that is the point of the design.

## 4. Database: SQLite

| File | Contents |
|---|---|
| `app.db` | `users`, `cases`, `jobs` |
| `case_xxx/faces.db` | Encrypted face crops, one file per case |

```
users: id, username, password_hash (Argon2), public_key, encrypted_private_key,
       failed_attempts, locked_until
cases: id, title, owner_id, folder_path, status, created_at
jobs:  id, case_id, status, progress, error
```

Enable WAL mode so the background job and API requests don't block each other, and set `check_same_thread=False` if you use threads.

## 5. API contract

| Method | Endpoint | Who | Purpose |
|---|---|---|---|
| POST | `/auth/register` | public | Create a user and generate their RSA key pair (rate-limited) |
| POST | `/auth/login` | public | Verify password, set httpOnly cookie, enforce lockout |
| POST | `/auth/logout` | user | Clear the session |
| GET | `/auth/me` | user | Current user |
| GET | `/cases` | user | List all cases, each with an `is_owner` flag |
| GET | `/cases/{id}/public` | user | Stream the blurred video (HTTP Range support) |
| GET | `/cases/{id}/verify` | user | Verify manifest signature and hashes |
| POST | `/cases` | user | Upload a video, become its owner, start the protect job |
| GET | `/jobs/{id}` | owner | Job progress |
| POST | `/cases/{id}/restore/start` | **owner only** | Re-enter password, return a single-use stream token |
| GET | `/restore/stream/{token}` | **owner only** | MJPEG stream of restored frames, in memory only |

## 6. Key design decisions

1. **Decryption stays on the server.** The browser never sees an AES key or private key.
2. **Step-up password for restore.** The password unlocks the owner's private key, which unwraps the DEK. The DEK lives in server memory under a single-use token with a short TTL (about 60 seconds) and is discarded after the stream ends.
3. **Restored frames never touch disk.** They stream as MJPEG and display in an `<img>` tag, with the username and timestamp watermarked in.
4. **Cookie sessions.** httpOnly, SameSite=Strict, plus a CSRF header check on state-changing requests.
5. **The protect pipeline runs as a background job**, and React polls for progress.
6. **Hardening basics:** CORS locked to the React origin, rate limiting on login and register, upload type and size checks, Pydantic validation, and generic login error messages.
7. **Demo packaging:** build the React app and serve it with FastAPI `StaticFiles`, so everything starts from one command. Seed two demo users (for example `alice` and `bob`).
I've replaced the week-by-week plan and the team split with a phase-wise plan. The rest of the plan is unchanged, apart from the small edits listed at the end.

## 7. Phase-wise plan

**Order of work:** Phase 1 comes first. Phases 2 and 3 can run in parallel, because the crypto work only needs sample face crops. Then 4, 5, 6, and 7 follow in sequence. Frontend scaffolding starts in Phase 1 against stub endpoints and continues alongside Phases 2-4.

### Phase 1: Foundation and design
**Goal:** Everything needed to build is decided and running.
- Finalize requirements, the threat model, and the API contract.
- Scaffold the FastAPI backend (stub endpoints) and the Vite React app, and generate the typed client from the OpenAPI schema.
- Set up the CUDA build of PyTorch and Ultralytics, and confirm `torch.cuda.is_available()`.
- Choose 2-3 test videos: a single face, a crowd, and fast motion or side profiles.
- When implementation is authorized, obtain or train WIDER FACE fine-tuned YOLO26n weights.
- Convert WIDER FACE to YOLO format and start the YOLO26n fine-tuning run.

**Deliverables:** design document, architecture diagram, API table, repo with both apps running.
**Exit criteria:** GPU confirmed, stub API reachable from React, training running.

### Phase 2: AI detection and blurring pipeline
**Goal:** Reliable face detection and a correctly blurred public video.
- Run YOLO26 on every frame on the GPU (low `conf`, larger `imgsz`, fp16).
- Pad boxes by 15-20% and clamp them to the frame edges.
- Apply heavy blur or pixelation.
- Gap-fill short detection misses from the previous frame so faces never flash through.
- Write `public.mp4` at the original fps and resolution, and assert the frame counts match.
- Label about 100 frames from your own videos, and evaluate the fine-tuned YOLO26n on those frames and on WIDER FACE val.

**Deliverables:** `detect.py`, `blur.py`, blurred demo videos, YOLO26n evaluation results.
**Exit criteria:** face coverage measured (target ≥ 95%), YOLO26n evaluated, frame counts identical.

### Phase 3: Cryptographic core
**Goal:** Face crops are protected, restorable only by the owner, and tamper-evident.
- Generate a random 256-bit DEK per video, and encrypt each PNG crop with AES-GCM (fresh nonce per crop, frame index and coordinates as AAD).
- Store crops in `faces.db`.
- Generate an RSA key pair per user, with the private key encrypted under their password.
- Wrap the DEK for the **owner only** in `keys.json`.
- Build the SHA-256 manifest and sign it.
- Write `restore.py`: verify the signature, unwrap the key, decrypt, and paste crops at the saved positions.
- Write unit tests for tamper cases (flipped byte, swapped video, wrong key).

**Deliverables:** `crypto/` modules, the command-line protect and restore round trip, unit tests.
**Exit criteria:** restored frames are pixel-identical to the originals, and every tamper test is rejected.

### Phase 4: Secure backend
**Goal:** The API enforces authentication and ownership.
- Create the SQLite schema (`users`, `cases`, `jobs`).
- Implement register and login with Argon2, lockout, rate limiting, httpOnly SameSite cookies, and a CSRF header check.
- Add the `require_owner(case_id)` dependency.
- Build the protect pipeline as a background job with a progress endpoint.
- Implement the step-up password flow, the single-use short-lived stream token, and the MJPEG restore stream (in memory only).
- Serve `public.mp4` with HTTP Range support.

**Deliverables:** every endpoint in the API contract, working and testable via `/docs`.
**Exit criteria:** a non-owner gets 403 on restore, the token works exactly once, and lockout triggers after repeated failures.

### Phase 5: Frontend and integration
**Goal:** The complete flow works end to end on the demo laptop.
- Build the pages: Login/Register, Case library ("Yours" badges), Case page (public player, plus the owner-only restore flow with a password prompt), and Upload with a progress bar.
- Add the verify badge, loading and error states.
- Feather the pasted face edges, and burn the username and timestamp watermark into restored frames.
- Seed demo users (for example `alice` and `bob`).
- Build the React app and serve it from FastAPI, so the demo starts with one command.

**Deliverables:** the working application.
**Exit criteria:** Alice uploads, Bob sees blurred video with no restore option, and Alice restores her faces, all from one running instance.

### Phase 6: Security testing and evaluation
**Goal:** Prove the system works and collect the numbers.
- Run the six attack demos (byte flip, video swap, non-owner API call, crypto-level denial, token replay, brute force) and capture screenshots.
- Compute the metrics table: mAP50, face coverage, fps, restoration fidelity, tamper detection, restore latency, storage overhead.
- Optionally export the model to TensorRT if the demo needs more speed.
- Fix the bugs found.

**Deliverables:** attack evidence, metrics table, bug-fix log.
**Exit criteria:** all attacks behave as designed, and all metrics are recorded.

### Phase 7: Documentation and demo readiness
**Goal:** Present with confidence.
- Write the report (problem, design, implementation, results, limitations).
- Build the slides around the 7-8 minute demo script.
- Record a backup demo video, and prepare a pre-processed case folder.
- Rehearse the full demo at least twice, including the attack segments.

**Deliverables:** final report, slides, backup video, clean repo with README.
**Exit criteria:** two clean rehearsals, and the demo runs from a fresh start.

**Priority rule if time runs short:** cut stretch goals first, then UI polish, then TensorRT. Never cut the crypto, the signature checks, or the ownership enforcement

## 8. Threat model

| Attacker | Goal | Defense |
|---|---|---|
| Logged-in non-owner | See someone else's faces | API ownership check (403), plus the key is wrapped only for the owner, so a bypass still yields only ciphertext |
| Database or disk thief | Read face crops | AES-256-GCM, and the key is recoverable only with the owner's password |
| Malicious editor | Alter the video or crops | Signed SHA-256 manifest, GCM tag, AAD binding |
| Stolen owner session cookie | Restore faces | Password re-entry for every restore, short-lived single-use token, watermark |
| Web attacker | Session theft, CSRF, XSS | httpOnly SameSite cookies, CSRF header, strict CORS |
| Password guesser | Break in | Argon2, lockout, rate limiting |
| Stream-link sharer | Replay a restore URL | Single-use token bound to the user |

**Limitations to state honestly:**
- There is no audit trail, so you can't review after the fact who restored what.
- The server briefly holds the key in memory during a restore. Moving decryption into the browser (WebCrypto) is future work.
- A compromised server is out of scope.
- The manifest is signed with a server-held key.

## 9. Attack demos

1. **Byte flip:** change one byte in `faces.db`, and GCM and the signature check both reject it.
2. **Video swap:** replace `public.mp4` with an edited copy, and manifest verification fails.
3. **Non-owner API call:** Bob calls `POST /cases/{id}/restore/start` on Alice's video (via `/docs` or curl) and gets 403.
4. **Crypto-level denial:** show that `keys.json` holds only Alice's wrapped key, and that Bob's key can't unwrap it even with a copy of the files.
5. **Token replay:** reuse a stream token, and it's rejected.
6. **Brute force:** repeated bad logins trigger lockout.

## 10. Evaluation metrics

| Metric | How to measure | Target |
|---|---|---|
| Detector accuracy (YOLO26n) | mAP50 on WIDER FACE val | Report measured mAP50 |
| Face coverage | % of faces fully covered by blur in your labeled frames | ≥ 95% |
| Detection speed | fps on your CUDA laptop (PyTorch fp16, and TensorRT if tried) | Report it |
| Restoration fidelity | Decrypted crop vs. original pixels | Identical (lossless) |
| Tamper detection | 20 tamper attempts | 100% detected |
| Restore latency | Click to first restored frame | Under 3 seconds |
| Storage overhead | `faces.db` size vs. source video | Report it |

## 11. Demo script (7-8 minutes)

1. **Problem (30s):** footage needs privacy, but the owner needs the originals.
2. **Architecture (1 min):** diagram, the three domains, and the YOLO26n evaluation slide.
3. **Alice uploads (1 min):** progress bar, with GPU speed shown.
4. **Bob logs in (1 min):** he sees Alice's video blurred, with no restore option.
5. **Alice restores (1.5 min):** verify badge, password prompt, watermarked restored stream.
6. **Attacks (2 min):** byte flip, Bob's direct API call, and the lockout.
7. **Results (1 min):** metrics table.
8. **Limitations and future work (30s).**

## 12. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Training takes too long or underperforms | Start YOLO26n fine-tuning early; evaluate a community WIDER FACE fine-tuned YOLO26n checkpoint if needed |
| Misses on small or profile faces | Larger `imgsz`, low `conf`, padded boxes, gap-fill, and honest recall reporting |
| GPU out of memory | Smaller batch for training, and fp16 inference |
| CUDA or driver mismatch | Verify the PyTorch CUDA build in Week 1 |
| Team new to React | Keep the UI to about 4 pages, use a component library, and test via `/docs` first |
| Cookie or CORS issues between Vite and FastAPI | Use Vite's dev proxy, and serve the built app from FastAPI for the demo |
| Seams in restored video | Feather the edges, or note it as a limitation |
| Live demo failure | Backup recording and a pre-processed case folder |

## 13. Stretch goals

- **Owner-granted sharing:** the owner wraps the DEK for a chosen user's public key (needs the owner's password).
- **Per-person selective restore** using a separate DEK per tracked face.
- **In-browser decryption** with WebCrypto, so the server never sees the key.
- **Blur strength test:** try a small learned model to reconstruct faces from your blur, and report how well your blur holds up.

## 14. Final deliverables checklist

- Source code, a README, and one-command run instructions
- Architecture diagram, API table, and threat model
- Training logs and the YOLO26n evaluation
- Attack screenshots and a metrics table
- Report (problem, design, implementation, results, limitations)
- Slides and a backup demo video
