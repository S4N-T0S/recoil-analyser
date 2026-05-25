"""recoil_analyser - extract weapon recoil patterns from FPS footage.

Defaults are tuned for The Finals, but it works for any first-person shooter by
adjusting FOV / distance / magazine / ROIs. See README.md for the recording
protocol and the analysis method.
"""

__version__ = "0.1.4"
__author__ = "S4N-T0S"
__url__ = "https://github.com/S4N-T0S/recoil-analyser"
__website__ = "https://s4nt0s.eu"

from .geometry import CameraGeometry

__all__ = ["CameraGeometry", "__version__"]
