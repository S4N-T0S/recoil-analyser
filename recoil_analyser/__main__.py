"""`python -m recoil_analyser` launches the GUI.

For headless / scripted use, call `python -m recoil_analyser.cli ...` instead.
"""

from .gui import main

if __name__ == "__main__":
    raise SystemExit(main())
