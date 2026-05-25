"""`python -m recoil_analyser` launches the GUI.

For headless / scripted use, call `python -m recoil_analyser.cli ...` instead.
"""

import sys

from .deps import dependency_error_message, missing_dependencies


def main() -> int:
    # Check before importing .gui: it pulls in cv2/numpy, which would otherwise crash
    missing = missing_dependencies()
    if missing:
        msg = dependency_error_message(missing)
        print(msg, file=sys.stderr)
        try:  # the user may have launched without a console
            from tkinter import Tk, messagebox

            root = Tk()
            root.withdraw()
            messagebox.showerror("Recoil Analyser - missing dependencies", msg)
            root.destroy()
        except Exception:
            pass
        return 1

    from .gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    raise SystemExit(main())
