# Proctoring for the interview backend

Camera checks (other people, phones, no face, head turned), tab-switch events, per-interview warnings, and a review
log that goes into the report. Reworked from your language-assessment proctoring code.

## 1. Add the files

```
app/proctoring/__init__.py
app/proctoring/analyzer.py     # YOLO + MediaPipe, returns what is in a frame
app/proctoring/session.py      # turns frames into warnings and a log, per interview
app/api/v1/proctoring.py       # the two routes
```

Install: `pip install -r requirements-proctoring.txt` (Python 3.11 or 3.12 recommended). Put `yolo11n.pt` next to
`analyzer.py`, or leave it out and Ultralytics downloads it on first use.

## 2. Wire it in (two small edits)

`app/api/v1/router.py`:

```python
from app.api.v1.proctoring import router as proctoring_router   # add

for route_group in (health_router, auth_router, resumes_router, jobs_router,
                    interviews_router, reports_router, extensions_router,
                    proctoring_router):                          # add
    api_router.include_router(route_group)
```

`app/api/v1/interviews.py`, so the report carries the review log:

```python
from app.proctoring.session import integrity_summary            # add near the other imports

# inside _report(), add one key to the returned dict:
            "integrity": integrity_summary(interview),
```

No other backend file changes. If these routes (or the libraries) are missing, the front end stops sending after one
try and the interview runs normally.

## 3. Routes

| Route | Purpose |
|---|---|
| `POST /interview/{id}/proctor/frame` | One camera frame (multipart field `file`). Returns `{status, violation, warning, warnings_used, warnings_max}`. |
| `POST /interview/{id}/proctor/event` | `{"type": "tab_hidden"}` or `{"type": "camera_unavailable"}`. |

Both need the candidate's login and only work on their own interview while it is `in_progress`.

## 4. Settings (environment variables, all optional)

| Variable | Default | Meaning |
|---|---|---|
| `PROCTOR_MAX_WARNINGS` | 3 | Warnings shown per interview. After that events are still logged, nothing more is shown. |
| `PROCTOR_YAW_MIN` / `PROCTOR_YAW_MAX` | 0.30 / 0.70 | Head-turn limits (0.5 = facing the camera). |
| `PROCTOR_PERSON_CONF` / `PROCTOR_DEVICE_CONF` | 0.5 / 0.45 | YOLO confidence needed to count a person or device. |
| `PROCTOR_DEVICE_LABELS` | `cell phone,laptop` | YOLO classes treated as devices. |
| `PROCTOR_SAVE_SNAPSHOTS` | off | `1` keeps the frame behind each finding. Then update the consent text and set a retention period. |

## 5. What is different from the old code, and why

- **Head turn.** The old "gaze" check compared the eye's position in the picture, so anyone sitting off-centre was
  flagged "Looking Left". It now uses the nose position between the face edges, and a finding must last about
  16 seconds. It is logged for review but never shown as a warning, because looking away while thinking is normal.
- **No face** is now a finding. Before, it counted as fine.
- **Per interview, not global.** One shared warning counter and one shared log file became state on each interview.
- **Findings need several frames in a row** (two for a person, device or no face), and each episode warns once.
- **Nothing ends the interview.** Warnings, then a log for the hiring team. Auto-ending on a false alarm punishes
  honest candidates. A person should decide.
- **`book` and `tv` are no longer flagged** (too many false alarms). Edit `PROCTOR_DEVICE_LABELS` to change it.
- **Frames are analysed and discarded** unless you turn on snapshots. The old code saved every suspicious frame
  with a one-second filename, so frames overwrote each other and none were tied to a person.
- **Blocking work no longer freezes the server.** The route is a plain `def`, so FastAPI runs it in a worker thread.
- **Login required, size limit, one frame per second per interview.** The old `/detect/` was open to anyone.

## 6. What I did not bring over

- **Audio proctoring.** It records the server's microphone (`sounddevice`), which only works when the server is on
  the candidate's own machine. Its "whispering" rule also fires on plain silence. For a web interview the browser
  has to capture the audio. Detecting a second voice is a different job from these noise checks.
- **`eye_model.h5`.** The file you attached is a Git LFS pointer (a 3-line text file), not the model, and none of the
  code you sent loads it.
- **Auth, JSON user files, Whisper, OpenAI helpers.** Not needed here. One warning: the other platform's `main.py`
  stores passwords in plain text in `users.json` and `/login` returns no token, so nothing is protected. Fix that
  before it has real users.

## 7. Before you rely on it

- I tested the logic, the routes and the fail-open behaviour with stand-in models. **I did not run real YOLO or
  MediaPipe**, because I don't have the weights or those libraries here. Try it with your webcam: sit normally,
  turn your head, bring a second person into view, hold up a phone, switch tabs.
- Tune `PROCTOR_YAW_MIN/MAX` and the confidence values on real recordings of real candidates.
- Findings are **signals for a human to review**, not proof. Glasses, lighting, a poster of a person or a laptop in
  the background can all trigger them.
- Interview data (including this log) is in memory, like the rest of the interview store, and is lost on restart.
- Add `proctoring_snapshots/`, `*.pt` and `.venv*/` to `.gitignore`.
- Consent text is in `src/config.js` on the front end. Have it checked against the privacy rules where you operate.
