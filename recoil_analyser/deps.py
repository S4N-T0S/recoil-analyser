"""Startup check that the required third-party packages are importable.

A missing dependency otherwise fails confusingly: cv2/numpy crash with a raw
ImportError traceback at import time, while matplotlib (imported lazily only
when a plot is drawn) fails *silently* - analysis runs but no plot ever
appears. Checking up front lets us report exactly what to install.

This module deliberately imports nothing heavy: ``find_spec`` checks
availability without importing the package, so it is safe to call before any
of cv2/numpy/matplotlib have been imported.
"""

from __future__ import annotations

import importlib.util

# Import name -> pip name. They differ for OpenCV (import cv2 / pip
# opencv-python). Keep in sync with requirements.txt.
_REQUIRED: dict[str, str] = {
    "cv2": "opencv-python",
    "numpy": "numpy",
    "matplotlib": "matplotlib",
}

# Extras for the OCR shot-detection method only (--method ocr). Checked
# separately so a missing/broken paddle install gives a clear message on the
# OCR path instead of a raw ImportError, while the core ammo/muzzle methods
# keep working.
_OCR_REQUIRED: dict[str, str] = {
    "paddle": "paddlepaddle",
    "paddleocr": "paddleocr",
}


def missing_dependencies() -> list[str]:
    """Return the pip names of required packages that cannot be imported."""
    return [pip for mod, pip in _REQUIRED.items() if importlib.util.find_spec(mod) is None]


def missing_ocr_dependencies() -> list[str]:
    """Return the pip names of OCR-method packages that cannot be imported."""
    return [pip for mod, pip in _OCR_REQUIRED.items() if importlib.util.find_spec(mod) is None]


def ocr_dependency_error_message(missing: list[str]) -> str:
    """A human-friendly message for missing OCR extras and how to install them."""
    return (
        f"The OCR ammo counter needs package(s): {', '.join(missing)}.\n\n"
        "Install everything with:\n"
        "    pip install -r requirements.txt\n\n"
        "Note: PaddlePaddle requires Python <= 3.13 (no 3.14 wheels yet).\n"
        "Or pick 'dumb ammo counter' / 'muzzle flash' instead."
    )


def dependency_error_message(missing: list[str]) -> str:
    """A human-friendly message listing what's missing and how to install it."""
    return (
        f"Missing required package(s): {', '.join(missing)}.\n\n"
        "Install everything with:\n"
        "    pip install -r requirements.txt\n\n"
        "or just the missing ones:\n"
        f"    pip install {' '.join(missing)}"
    )
