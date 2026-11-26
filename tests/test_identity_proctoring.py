import os
os.environ["TESTING_ENV"] = "1"
try:
    import pytest
except ImportError:
    pytest = None
import numpy as np
import cv2
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app.services.store import USERS, SESSIONS, INTERVIEWS, REPORTS
from backend.app.proctoring.analyzer import (
    FACE_ANCHORS,
    extract_face_descriptor,
    compare_face_descriptors,
)
from backend.app.proctoring.session import (
    set_baseline,
    apply_observation,
    integrity_summary,
)

client = TestClient(app)


def test_health_endpoint_supports_render_probes():
    assert client.get("/health").status_code == 200
    assert client.head("/health").status_code == 200


class MockLandmark:
    def __init__(self, x: float, y: float, z: float):
        self.x = x
        self.y = y
        self.z = z


def _generate_synthetic_face(seed: int = 42, noise: float = 0.0):
    np.random.seed(seed)
    coords = np.random.randn(468, 3).astype(np.float32) * 0.15
    # Anatomical anchors
    coords[10] = [0.0, -0.4, 0.0]    # forehead
    coords[152] = [0.0, 0.4, 0.0]    # chin
    coords[168] = [0.0, -0.1, 0.0]   # nose bridge
    coords[1] = [0.0, 0.05, 0.1]     # nose tip
    coords[33] = [-0.2, -0.1, 0.0]   # left eye
    coords[263] = [0.2, -0.1, 0.0]   # right eye
    coords[61] = [-0.15, 0.25, 0.0]  # left mouth
    coords[291] = [0.15, 0.25, 0.0]  # right mouth
    coords[234] = [-0.35, 0.0, 0.0]  # left cheek
    coords[454] = [0.35, 0.0, 0.0]   # right cheek

    if noise > 0:
        coords += np.random.randn(468, 3).astype(np.float32) * noise

    return [MockLandmark(float(pt[0]), float(pt[1]), float(pt[2])) for pt in coords]


def _generate_different_person():
    np.random.seed(999)
    coords_b = np.random.randn(468, 3).astype(np.float32) * 0.2
    coords_b[10] = [0.0, -0.3, 0.0]
    coords_b[152] = [0.0, 0.55, 0.0]
    coords_b[168] = [0.0, -0.05, 0.0]
    coords_b[1] = [0.0, 0.15, 0.1]
    coords_b[33] = [-0.12, -0.05, 0.0]  # narrow eyes
    coords_b[263] = [0.12, -0.05, 0.0]
    coords_b[61] = [-0.28, 0.2, 0.0]   # much wider mouth
    coords_b[291] = [0.28, 0.2, 0.0]
    coords_b[234] = [-0.48, 0.05, 0.0] # wider cheeks
    coords_b[454] = [0.48, 0.05, 0.0]
    return [MockLandmark(float(pt[0]), float(pt[1]), float(pt[2])) for pt in coords_b]


def test_face_descriptor_same_person():
    lm1 = _generate_synthetic_face(seed=42)
    lm2 = _generate_synthetic_face(seed=42, noise=0.005)  # same person, slight movement

    desc1 = extract_face_descriptor(lm1)
    desc2 = extract_face_descriptor(lm2)

    similarity, is_match = compare_face_descriptors(desc1, desc2)
    assert is_match is True
    assert similarity >= 0.85, f"Expected similarity >= 0.85, got {similarity}"


def test_face_descriptor_different_person():
    lm_person_a = _generate_synthetic_face(seed=42)
    lm_person_b = _generate_different_person()

    desc_a = extract_face_descriptor(lm_person_a)
    desc_b = extract_face_descriptor(lm_person_b)

    similarity, is_match = compare_face_descriptors(desc_a, desc_b)
    assert is_match is False, f"Expected mismatch for Person B, but got similarity {similarity}"
    assert similarity < 0.86


def test_session_person_swap_detection():
    interview = {
        "id": "iv_swap_test",
        "user_id": "u_test",
        "status": "in_progress",
        "proctoring": {"events": [], "warnings": 0},
    }

    lm_a = _generate_synthetic_face(seed=42)
    desc_a = extract_face_descriptor(lm_a)

    # Set baseline identity
    set_baseline(interview, desc_a)

    # Frame 1 with Person A: matches baseline, no violation
    obs_a = {
        "faces": 1,
        "people": 1,
        "devices": [],
        "yaw": 0.5,
        "face_descriptor": desc_a,
    }
    res1 = apply_observation(interview, obs_a)
    assert res1["violation"] is None
    assert res1["warnings_used"] == 0

    # Person B takes over the camera
    lm_b = _generate_different_person()
    desc_b = extract_face_descriptor(lm_b)

    obs_b = {
        "faces": 1,
        "people": 1,
        "devices": [],
        "yaw": 0.5,
        "face_descriptor": desc_b,
    }

    # Frame 1 of Person B: streak starts (NEEDED['different_person'] = 2)
    res_b1 = apply_observation(interview, obs_b)
    assert res_b1["violation"] is None

    # Frame 2 of Person B: threshold reached -> triggers different_person violation!
    res_b2 = apply_observation(interview, obs_b)
    assert res_b2["violation"] == "different_person"
    assert "different person" in res_b2["warning"].lower()
    assert res_b2["warnings_used"] == 1

    # Check integrity summary report
    summary = integrity_summary(interview)
    assert summary["baseline_captured"] is True
    assert summary["by_type"]["different_person"] == 1
    assert summary["integrity_verdict"] == "Action Required: Identity Mismatch"
    assert summary["integrity_score"] < 100


def test_device_detection_warning():
    interview = {
        "id": "iv_device_test",
        "user_id": "u_test",
        "status": "in_progress",
        "proctoring": {"events": [], "warnings": 0},
    }
    obs_device = {
        "faces": 1,
        "people": 1,
        "devices": ["cell phone"],
        "yaw": 0.5,
        "face_descriptor": None,
    }
    # Device detection has NEEDED["device"] = 1, so 1 frame triggers warning
    res = apply_observation(interview, obs_device)
    assert res["violation"] == "device"
    assert "phone" in res["warning"].lower()
    assert res["warnings_used"] == 1


def test_baseline_api_endpoints():

    USERS["u_base_user"] = {"id": "u_base_user", "email": "base@test.com", "name": "Candidate Base", "role": "candidate"}
    SESSIONS["tok_base_user"] = "u_base_user"
    INTERVIEWS["iv_base_test"] = {
        "id": "iv_base_test",
        "user_id": "u_base_user",
        "status": "draft",
        "proctoring": {"events": [], "warnings": 0},
    }

    # Frame with no face (blank image) should be rejected if model available, or return unavailable
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    _, buf_blank = cv2.imencode(".jpg", blank)
    res_err = client.post(
        "/api/v1/interview/iv_base_test/proctor/baseline",
        headers={"Authorization": "Bearer tok_base_user"},
        files={"file": ("baseline.jpg", buf_blank.tobytes(), "image/jpeg")},
    )
    if res_err.status_code == 200:
        assert res_err.json()["status"] == "unavailable"
    else:
        assert res_err.status_code == 422
        assert "No face detected" in res_err.json()["detail"]


if __name__ == "__main__":
    print("Running test_face_descriptor_same_person...")
    test_face_descriptor_same_person()
    print("PASS: test_face_descriptor_same_person")

    print("Running test_face_descriptor_different_person...")
    test_face_descriptor_different_person()
    print("PASS: test_face_descriptor_different_person")

    print("Running test_session_person_swap_detection...")
    test_session_person_swap_detection()
    print("PASS: test_session_person_swap_detection")

    print("Running test_baseline_api_endpoints...")
    test_baseline_api_endpoints()
    print("PASS: test_baseline_api_endpoints")

    print("\nALL IDENTITY PROCTORING TESTS PASSED SUCCESSFULLY!")
