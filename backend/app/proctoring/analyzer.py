"""Camera-frame checks for interviews.

Place at: app/proctoring/analyzer.py

Reworked from the old face_object_proctoring.py. What changed and why:

  * It only OBSERVES: it returns what is in the frame and nothing else. It does not log, count warnings or write
    files. session.py does that per interview (the old code used one global counter and one shared log file).
  * Head turn is measured from the nose position between the two face edges. The old "gaze" test compared the
    eye's position in the PICTURE, so anyone sitting a little off-centre was flagged "Looking Left/Right".
  * "No face in view" is now a finding (the old code treated it as fine).
  * A lock around the models: MediaPipe's FaceMesh object is not safe for two requests at the same time.
  * Class names come from the model itself, not a hard-coded list. "book" and "tv" are no longer flagged.
  * If the libraries or weights are missing, ProctoringUnavailable is raised and the interview carries on
    without checks. A missing model must never break someone's interview.

Settings (environment variables, all optional):
  PROCTOR_YOLO_WEIGHTS      path or name of the YOLO weights (default yolo11n.pt, looked up next to this file first)
  PROCTOR_PERSON_CONF       minimum confidence to count a person (default 0.5)
  PROCTOR_DEVICE_CONF       minimum confidence to count a device (default 0.10)
  PROCTOR_DEVICE_LABELS     comma-separated YOLO classes treated as devices (default includes phone aliases)
  PROCTOR_IMAGE_SIZE        YOLO inference size (default 960; higher helps small handheld devices)
  PROCTOR_DETECTION_FLOOR   minimum YOLO score returned for diagnostics (default 0.10)
"""
from __future__ import annotations

import logging
import os
import threading

log = logging.getLogger(__name__)

YOLO_WEIGHTS = os.getenv("PROCTOR_YOLO_WEIGHTS", "yolo11n.pt")
PERSON_CONF = float(os.getenv("PROCTOR_PERSON_CONF", "0.5"))
DEVICE_CONF = float(os.getenv("PROCTOR_DEVICE_CONF", "0.10"))
DEVICE_LABELS = {
    "cell phone", "mobile phone", "mobile", "smartphone", "phone", "laptop",
}
DEVICE_LABELS.update(
    s.strip().lower()
    for s in os.getenv("PROCTOR_DEVICE_LABELS", "").split(",")
    if s.strip()
)
IMAGE_SIZE = int(os.getenv("PROCTOR_IMAGE_SIZE", "960"))
DETECTION_FLOOR = float(os.getenv("PROCTOR_DETECTION_FLOOR", "0.10"))

# MediaPipe face-mesh landmark numbers: nose tip, and the two outer edges of the face.
NOSE_TIP, FACE_EDGE_A, FACE_EDGE_B = 1, 234, 454


class FrameError(Exception):
    """The uploaded image could not be read."""


class ProctoringUnavailable(Exception):
    """The detection libraries or weights are not installed or failed to load."""


_cache = None
_load_error: str | None = None
_load_lock = threading.Lock()
_infer_lock = threading.Lock()


def _models():
    """Load YOLO and FaceMesh once. A failed load is remembered so every frame doesn't retry it."""
    global _cache, _load_error
    if _cache is not None:
        return _cache
    if _load_error:
        raise ProctoringUnavailable(_load_error)
    with _load_lock:
        if _cache is not None:
            return _cache
        if _load_error:
            raise ProctoringUnavailable(_load_error)
        try:
            import mediapipe as mp
            from ultralytics import YOLO

            local = os.path.join(os.path.dirname(__file__), YOLO_WEIGHTS)
            yolo = YOLO(local if os.path.exists(local) else YOLO_WEIGHTS)
            mesh = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2)
            _cache = (yolo, mesh)
        except Exception as exc:  # missing package, missing weights, unsupported Python version...
            _load_error = f"Proctoring models could not be loaded: {exc}"
            log.error(_load_error)
            raise ProctoringUnavailable(_load_error) from exc
    return _cache


def head_yaw_ratio(landmarks) -> float | None:
    """Where the nose sits between the two face edges: about 0.5 when facing the camera, toward 0 or 1 when turned."""
    a, b, nose = landmarks[FACE_EDGE_A].x, landmarks[FACE_EDGE_B].x, landmarks[NOSE_TIP].x
    if abs(b - a) < 1e-3:
        return None
    return float((nose - a) / (b - a))


def analyze_frame(data: bytes) -> dict:
    """Return {"faces": int, "people": int, "devices": [str], "yaw": float | None} for one JPEG/PNG frame."""
    # These are optional, heavyweight proctoring dependencies. Keep them out of
    # module import so the rest of the API can start without the proctoring extra.
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ProctoringUnavailable(
            "Proctoring dependencies are not installed; install the proctoring extra."
        ) from exc

    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise FrameError("The image could not be read.")

    yolo, mesh = _models()
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    with _infer_lock:
        mesh_result = mesh.process(rgb)
        detections = yolo.predict(
            frame, verbose=False,
            conf=min(PERSON_CONF, DEVICE_CONF, DETECTION_FLOOR), imgsz=IMAGE_SIZE,
        )

    faces = list(mesh_result.multi_face_landmarks or [])

    people = 0
    devices: set[str] = set()
    device_scores: list[dict] = []
    object_scores: list[dict] = []
    for result in detections:
        classes = result.boxes.cls.cpu().numpy().astype(int)
        scores = result.boxes.conf.cpu().numpy()
        for cls, score in zip(classes, scores):
            label = str(yolo.names[int(cls)]).strip().lower()
            if score >= 0.15:
                object_scores.append({"label": label, "confidence": round(float(score), 3)})
            if label == "person" and score >= PERSON_CONF:
                people += 1
            elif label in DEVICE_LABELS:
                device_scores.append({"label": label, "confidence": round(float(score), 3)})
                if score >= DEVICE_CONF:
                    devices.add(label)

    yaw = head_yaw_ratio(faces[0].landmark) if len(faces) == 1 else None
    return {
        "faces": len(faces), "people": people, "devices": sorted(devices),
        "device_scores": device_scores, "objects": object_scores,
        "image_size": [int(frame.shape[1]), int(frame.shape[0])], "yaw": yaw,
    }
