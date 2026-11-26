import builtins

import pytest

from backend.app.main import app
from backend.app.proctoring import analyzer


def test_api_imports_without_proctoring_dependencies() -> None:
    assert app is not None


def test_missing_image_dependencies_report_proctoring_unavailable(monkeypatch) -> None:
    real_import = builtins.__import__

    def import_without_proctoring_images(name, *args, **kwargs):
        if name in {"cv2", "numpy"}:
            raise ModuleNotFoundError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_proctoring_images)

    with pytest.raises(analyzer.ProctoringUnavailable, match="image dependencies"):
        analyzer.analyze_frame(b"")
