"""Per-interview proctoring state: turns what the camera sees into warnings and a review log.

Place at: app/proctoring/session.py

The state lives on the interview record (interview["proctoring"]), next to the answers, so it is stored wherever
the interview is stored. Frames arrive every few seconds, so a finding must show up in several frames in a row
before it counts (one blurry frame is not a violation), and each episode warns once.

Settings (environment variables, all optional):
  PROCTOR_MAX_WARNINGS     warning limit per interview (default 3). Reaching it terminates the interview.
  PROCTOR_YAW_MIN / _MAX   head-turn limits (default 0.30 / 0.70; 0.5 is facing the camera). Tune on real recordings.
  PROCTOR_SAVE_SNAPSHOTS   "1" to keep the frame that triggered a finding (default off: frames are analysed and
                           discarded). If you turn this on, update the consent text and decide how long to keep them.
  PROCTOR_SNAPSHOT_DIR     where snapshots go (default proctoring_snapshots/)
"""
from __future__ import annotations

import os
import re
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

try:
    from backend.app.proctoring.analyzer import compare_face_descriptors
except ImportError:
    def compare_face_descriptors(d1: dict | None, d2: dict | None) -> tuple[float, bool]:
        return 1.0, True

MAX_WARNINGS = int(os.getenv("PROCTOR_MAX_WARNINGS", "5"))
YAW_MIN = float(os.getenv("PROCTOR_YAW_MIN", "0.30"))
YAW_MAX = float(os.getenv("PROCTOR_YAW_MAX", "0.70"))
SAVE_SNAPSHOTS = os.getenv("PROCTOR_SAVE_SNAPSHOTS", "0") == "1"
SNAPSHOT_DIR = Path(os.getenv("PROCTOR_SNAPSHOT_DIR", "proctoring_snapshots"))

MIN_FRAME_GAP = 0.8   # seconds; faster frames are skipped so one client can't hog the CPU
EVENT_GAP = 5.0       # seconds; the same browser event twice in a row is recorded once
WARNING_COOLDOWN = float(os.getenv("PROCTOR_WARN_COOLDOWN", "20.0"))  # minimum seconds between warnings

# Frames in a row (about 2 s apart) before a finding counts.
NEEDED = {"no_face": 2, "different_person": 2, "multiple_people": 2, "device": 1, "head_turned": 3}
# Checked in this order; the first new one in a frame is the one the candidate is warned about.
PRIORITY = ["multiple_people", "different_person", "device", "no_face", "head_turned"]
# Looking away is normal while thinking, so it is recorded for review but never shown as a warning.
WARN_KINDS = {"multiple_people", "different_person", "device", "no_face", "tab_hidden", "camera_unavailable"}
EVENT_KINDS = {"tab_hidden", "camera_unavailable"}

MESSAGES = {
    "multiple_people": "More than one person is in view. Please make sure you are alone.",
    "different_person": "Identity mismatch: A different person appears to be in view. Please ensure the registered candidate is taking the interview.",
    "device": "A phone or another device is in view. Please put it out of sight.",
    "no_face": "We can't see your face. Please sit in front of the camera.",
    "tab_hidden": "You left the interview tab. Please stay on this page during the interview.",
    "camera_unavailable": "Your camera isn't available. Please turn it on so the interview can continue.",
}


def _state(interview: dict) -> dict:
    st = interview.setdefault("proctoring", {})
    st.setdefault("events", [])
    st.setdefault("warnings", 0)
    st.setdefault("streak", {})
    st.setdefault("active", {})
    st.setdefault("last_frame", 0.0)
    st.setdefault("last_event", {})
    st.setdefault("last_warning_time", 0.0)
    st.setdefault("baseline", None)
    st.setdefault("baseline_at", None)
    return st


def set_baseline(interview: dict, desc: dict, image_data: bytes | None = None) -> None:
    """Store reference face descriptor and optionally save baseline portrait."""
    st = _state(interview)
    st["baseline"] = desc
    st["baseline_at"] = datetime.now(UTC).isoformat()
    interview_id = interview.get("id", "")
    if image_data and re.fullmatch(r"[A-Za-z0-9_-]+", interview_id):
        folder = SNAPSHOT_DIR / interview_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "baseline.jpg").write_bytes(image_data)
        st["has_baseline_image"] = True


def _add_event(st: dict, kind: str, detail: dict | None = None, frames: int = 1) -> int:
    event = {"type": kind, "at": datetime.now(UTC).isoformat(), "frames": frames}
    if detail:
        event["detail"] = detail
    st["events"].append(event)
    return len(st["events"]) - 1


def _warn(st: dict, kind: str | None, now: float | None = None) -> str | None:
    if not kind or kind not in WARN_KINDS:
        return None
    now = time.monotonic() if now is None else now
    last_warn = st.get("last_warning_time", 0.0)
    if last_warn and now - last_warn < WARNING_COOLDOWN:
        return None
    if st.get("warnings", 0) < MAX_WARNINGS:
        st["warnings"] = st.get("warnings", 0) + 1
        st["last_warning_time"] = now
        return MESSAGES.get(kind, "Proctoring guideline violation detected.")
    return None


def _response(st: dict, violation: str | None, warning: str | None) -> dict:
    return {"status": "ok", "violation": violation, "warning": warning,
            "warnings_used": st.get("warnings", 0), "warnings_max": MAX_WARNINGS}


def accept_frame(interview: dict, now: float | None = None) -> bool:
    """False if the last frame was too recent. Call before the expensive analysis."""
    now = time.monotonic() if now is None else now
    st = _state(interview)
    last_frame = st.get("last_frame", 0.0)
    if last_frame and now - last_frame < MIN_FRAME_GAP:
        return False
    st["last_frame"] = now
    return True


def apply_observation(interview: dict, obs: dict, now: float | None = None) -> dict:
    """Fold one analysed frame into the interview's state. Returns what the browser should show."""
    now = time.monotonic() if now is None else now
    st = _state(interview)

    diff_person = False
    sim_score = None
    if obs["faces"] == 1 and obs.get("face_descriptor"):
        baseline = st.get("baseline")
        if baseline is None:
            # Auto-enroll the candidate from the first clear single-face frame if not captured in setup
            set_baseline(interview, obs["face_descriptor"])
        else:
            sim, is_match = compare_face_descriptors(obs["face_descriptor"], baseline)
            sim_score = sim
            if not is_match:
                diff_person = True

    flags = {
        "no_face": obs["faces"] == 0,
        "multiple_people": obs["faces"] > 1 or obs["people"] > 1,
        "different_person": diff_person,
        "device": bool(obs["devices"]),
        "head_turned": obs["yaw"] is not None and not (YAW_MIN <= obs["yaw"] <= YAW_MAX),
    }
    detail = {
        "multiple_people": {"faces": obs["faces"], "people": obs["people"]},
        "different_person": {"similarity": sim_score},
        "device": {"devices": obs["devices"]},
    }

    new_kind = None
    for kind in PRIORITY:
        if flags[kind]:
            st["streak"][kind] = st["streak"].get(kind, 0) + 1
            if kind in st["active"]:
                st["events"][st["active"][kind]]["frames"] += 1  # same episode still going
            elif st["streak"][kind] >= NEEDED[kind]:
                # frames = the run of frames that triggered it, so the log shows how long it really lasted
                st["active"][kind] = _add_event(st, kind, detail.get(kind), frames=st["streak"][kind])
                if new_kind is None:
                    new_kind = kind
        else:
            st["streak"][kind] = 0
            st["active"].pop(kind, None)
    return _response(st, new_kind, _warn(st, new_kind, now=now))


def apply_event(interview: dict, kind: str, now: float | None = None) -> dict:
    """Record an event reported by the browser itself (tab hidden, camera unavailable)."""
    if kind not in EVENT_KINDS:
        raise ValueError(f"Unknown event: {kind}")
    now = time.monotonic() if now is None else now
    st = _state(interview)
    last = st["last_event"].get(kind)
    if last is not None and now - last < EVENT_GAP:
        return {"status": "skipped"}
    st["last_event"][kind] = now
    _add_event(st, kind)
    return _response(st, kind, _warn(st, kind, now=now))


def save_snapshot(interview_id: str, kind: str, data: bytes) -> None:
    """Keep the frame behind a finding, only if PROCTOR_SAVE_SNAPSHOTS=1."""
    if not SAVE_SNAPSHOTS or not re.fullmatch(r"[A-Za-z0-9_-]+", interview_id):
        return
    folder = SNAPSHOT_DIR / interview_id
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    (folder / f"{stamp}_{kind}_{secrets.token_hex(3)}.jpg").write_bytes(data)


def integrity_summary(interview: dict) -> dict:
    """For the report: counts by type, trust score, and the most recent events."""
    st = interview.get("proctoring")
    if not st:
        return {
            "checked": False,
            "flags": 0,
            "warnings": 0,
            "by_type": {},
            "events": [],
            "integrity_score": 100,
            "integrity_verdict": "Clean Session",
        }
    by_type: dict[str, int] = {}
    for event in st["events"]:
        by_type[event["type"]] = by_type.get(event["type"], 0) + 1
    warnings = st["warnings"]
    flags = len(st["events"])
    integrity_score = max(0, 100 - (warnings * 20 + flags * 5))
    if by_type.get("different_person", 0) > 0:
        integrity_verdict = "Action Required: Identity Mismatch"
    elif warnings == 0 and flags <= 1:
        integrity_verdict = "Clean Session"
    elif warnings >= 3:
        integrity_verdict = "Action Required: Suspicious"
    else:
        integrity_verdict = "Minor Flags Logged"

    return {
        "checked": True,
        "flags": flags,
        "warnings": warnings,
        "by_type": by_type,
        "events": st["events"][-50:],
        "integrity_score": integrity_score,
        "integrity_verdict": integrity_verdict,
        "baseline_captured": bool(st.get("baseline")),
        "has_baseline_image": bool(st.get("has_baseline_image")),
    }
