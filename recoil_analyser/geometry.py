"""Pinhole-camera conversions between screen pixels, view angle, and
centimetres measured on the wall the player is shooting at.

Recoil is fundamentally an *angular* quantity (the view rotates). Pixels and
centimetres both depend on capture settings, but degrees do not, so the angular
figures are the resolution/FOV-independent ground truth.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class CameraGeometry:
    """Maps screen-space displacement to physical/angular displacement.

    Attributes:
        width:      capture width in pixels (e.g. 2560).
        height:     capture height in pixels (e.g. 1440).
        fov_deg:    in-game field-of-view setting (The Finals default 81).
        fov_axis:   which axis ``fov_deg`` is measured along. The Finals reports
                    a vertical FOV, so "vertical" is the default. Supported:
                    "horizontal", "vertical", "diagonal".
        distance_m: player-to-wall distance in metres (recording protocol: 13).
    """

    width: int
    height: int
    fov_deg: float = 81.0
    fov_axis: str = "vertical"
    distance_m: float = 13.0

    @property
    def focal_px(self) -> float:
        """Focal length in pixels for the pinhole model (square pixels)."""
        half = math.tan(math.radians(self.fov_deg) / 2.0)
        if self.fov_axis == "horizontal":
            return (self.width / 2.0) / half
        if self.fov_axis == "vertical":
            return (self.height / 2.0) / half
        if self.fov_axis == "diagonal":
            diag = math.hypot(self.width, self.height)
            return (diag / 2.0) / half
        raise ValueError(f"Unknown fov_axis: {self.fov_axis!r}")

    def px_to_deg(self, dx: float, dy: float) -> tuple[float, float]:
        """Pixel displacement -> angular displacement in degrees (x, y)."""
        f = self.focal_px
        return (
            math.degrees(math.atan2(dx, f)),
            math.degrees(math.atan2(dy, f)),
        )

    def px_to_cm(self, dx: float, dy: float) -> tuple[float, float]:
        """Pixel displacement -> displacement on the wall plane, in cm (x, y).

        ``dx / focal_px`` is exactly ``tan(angle)``, so on a plane ``distance_m``
        away the lateral offset is ``distance_m * dx / focal_px`` (no
        small-angle approximation for the in-plane component).
        """
        f = self.focal_px
        d_cm = self.distance_m * 100.0
        return (d_cm * dx / f, d_cm * dy / f)
