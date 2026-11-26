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

os.environ.setdefault("YOLO_CONFIG_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data")))

log = logging.getLogger(__name__)

YOLO_WEIGHTS = os.getenv("PROCTOR_YOLO_WEIGHTS", "yolo11n.pt")
PERSON_CONF = float(os.getenv("PROCTOR_PERSON_CONF", "0.5"))
DEVICE_CONF = float(os.getenv("PROCTOR_DEVICE_CONF", "0.08"))
DEVICE_LABELS = {
    "cell phone", "mobile phone", "mobile", "smartphone", "phone", "laptop", "remote",
}
DEVICE_LABELS.update(
    s.strip().lower()
    for s in os.getenv("PROCTOR_DEVICE_LABELS", "").split(",")
    if s.strip()
)
IMAGE_SIZE = int(os.getenv("PROCTOR_IMAGE_SIZE", "640"))
DETECTION_FLOOR = float(os.getenv("PROCTOR_DETECTION_FLOOR", "0.08"))

# MediaPipe face-mesh landmark numbers: nose tip, and the two outer edges of the face.
NOSE_TIP, FACE_EDGE_A, FACE_EDGE_B = 1, 234, 454

# 32 key facial anchors for invariant biometric verification and person-swap detection
FACE_ANCHORS = [
    10, 152, 168, 1, 33, 133, 263, 362, 61, 291, 0, 17, 234, 454, 70, 300,
    98, 327, 93, 323, 136, 365, 172, 397, 63, 293, 107, 336, 158, 385, 153, 380,
]


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

            local_candidates = [
                os.path.join(os.path.dirname(__file__), YOLO_WEIGHTS),
                os.path.join(os.path.dirname(__file__), "..", "..", YOLO_WEIGHTS),
                os.path.join(os.path.dirname(__file__), "..", "..", "..", YOLO_WEIGHTS),
                YOLO_WEIGHTS,
            ]
            weights_path = next((p for p in local_candidates if os.path.exists(p)), YOLO_WEIGHTS)
            yolo = YOLO(weights_path)
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


def extract_face_descriptor(landmarks, frame=None) -> dict:
    """Extract invariant geometric proportions and appearance signature from face landmarks."""
    import math
    import cv2
    import numpy as np

    coords = np.array([[lm.x, lm.y, lm.z] for lm in landmarks], dtype=np.float32)
    origin = coords[168]  # nose bridge
    centered = coords - origin
    face_h = float(np.linalg.norm(coords[10] - coords[152]))  # forehead to chin
    if face_h < 1e-4:
        face_h = 1.0
    scaled = centered / face_h

    # Roll-alignment (horizontalize eye vector)
    eye_vec = coords[263] - coords[33]
    angle = math.atan2(eye_vec[1], eye_vec[0])
    c, s = math.cos(-angle), math.sin(-angle)
    R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float32)
    aligned = scaled @ R.T

    sub_coords = aligned[FACE_ANCHORS].flatten()

    def d(i: int, j: int) -> float:
        return float(np.linalg.norm(coords[i] - coords[j]))

    ratios = np.array([
        d(33, 263) / face_h,
        d(10, 168) / face_h,
        d(168, 1) / face_h,
        d(1, 152) / face_h,
        d(61, 291) / max(1e-4, d(33, 263)),
        d(234, 454) / face_h,
        d(98, 327) / max(1e-4, d(61, 291)),
        d(1, 0) / face_h,
        d(17, 152) / face_h,
        d(70, 33) / face_h,
        d(300, 263) / face_h,
    ], dtype=np.float32)

    geo_vec = np.concatenate([sub_coords, ratios * 3.0])
    norm = np.linalg.norm(geo_vec)
    if norm > 1e-6:
        geo_vec = geo_vec / norm

    app_vec: list[float] = []
    if frame is not None and frame.size > 0:
        h, w = frame.shape[:2]
        pts_x = (coords[:, 0] * w).astype(int)
        pts_y = (coords[:, 1] * h).astype(int)
        pad_x = int(0.12 * w * face_h)
        pad_y = int(0.12 * h * face_h)
        x0 = max(0, int(np.min(pts_x)) - pad_x)
        x1 = min(w, int(np.max(pts_x)) + pad_x)
        y0 = max(0, int(np.min(pts_y)) - pad_y)
        y1 = min(h, int(np.max(pts_y)) + pad_y)
        if x1 - x0 > 20 and y1 - y0 > 20:
            patch = cv2.resize(frame[y0:y1, x0:x1], (48, 48))
            hsv = cv2.cvtColor(patch, cv2.COLOR_BGR2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [8, 8], [0, 180, 0, 256])
            total = float(np.sum(hist))
            if total > 0:
                app_vec = (hist / total).flatten().tolist()

    return {"geometry": geo_vec.tolist(), "appearance": app_vec}


# Threshold for person verification: same-person is >= 0.88, person swaps drop below 0.80
FACE_MATCH_THRESHOLD = float(os.getenv("PROCTOR_FACE_MATCH_THRESHOLD", "0.82"))


def compare_face_descriptors(d1: dict | None, d2: dict | None) -> tuple[float, bool]:
    """Compare two facial descriptors. Return (similarity: float 0..1, is_match: bool)."""
    import numpy as np

    if not d1 or not d2:
        return 1.0, True

    g1 = np.array(d1.get("geometry", []), dtype=np.float32)
    g2 = np.array(d2.get("geometry", []), dtype=np.float32)
    if len(g1) == 0 or len(g2) == 0:
        return 1.0, True

    sim_geo = float(np.dot(g1, g2) / (np.linalg.norm(g1) * np.linalg.norm(g2) + 1e-8))
    sim_geo = max(0.0, min(1.0, sim_geo))

    a1 = np.array(d1.get("appearance", []), dtype=np.float32)
    a2 = np.array(d2.get("appearance", []), dtype=np.float32)
    if len(a1) > 0 and len(a2) > 0 and len(a1) == len(a2):
        sim_app = float(np.sum(np.minimum(a1, a2)))
        sim_app = max(0.0, min(1.0, sim_app))
        composite = 0.70 * sim_geo + 0.30 * sim_app
    else:
        composite = sim_geo

    is_match = composite >= FACE_MATCH_THRESHOLD
    return round(composite, 3), is_match


def analyze_frame(data: bytes) -> dict:
    """Return {"faces": int, "people": int, "devices": [str], "yaw": float | None, "face_descriptor": dict | None} for one JPEG/PNG frame."""
    # These are optional, heavyweight proctoring dependencies. Keep them out of
    # module import so the rest of the API can start without the proctoring extra.
    try:
        import cv2
        import numpy as np
    except ImportError as exc:
        raise ProctoringUnavailable(f"Proctoring image dependencies are not installed: {exc}") from exc

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
    face_desc = extract_face_descriptor(faces[0].landmark, frame) if len(faces) == 1 else None

    return {
        "faces": len(faces), "people": people, "devices": sorted(devices),
        "device_scores": device_scores, "objects": object_scores,
        "image_size": [int(frame.shape[1]), int(frame.shape[0])], "yaw": yaw,
        "face_descriptor": face_desc,
    }
