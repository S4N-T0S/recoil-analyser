"""Tkinter front-end: collect parameters, pick ROIs, run, save, summarise.

The parameter form is Tkinter; region picking uses OpenCV's drag-box selector
(see roi_select). Analysis runs on the UI thread (fine for a single clip) with
progress shown in a status label and the console.
"""

from __future__ import annotations

import traceback
import webbrowser
from pathlib import Path
from tkinter import (
    BooleanVar,
    Canvas,
    Entry,
    PhotoImage,
    StringVar,
    Text,
    Tk,
    Toplevel,
    filedialog,
    messagebox,
    ttk,
)

from . import __author__, __website__
from .core import AnalysisConfig, analyse
from .deps import missing_ocr_dependencies, ocr_dependency_error_message
from .export import save_json, save_plot
from .roi_select import first_frame, select_roi_scaled

# On-image guidance shown in each ROI popup. First line is the headline; the
# rest explain how tight the box should be. A little margin is fine; never
# include moving things (crosshair, gun, muzzle flash) in a tracking ROI.
ROI_HELP = {
    "tag": [
        "DRAG a box around the WALL TAG, then press ENTER (ESC = cancel)",
        "Cover the whole sticker + a little white margin. A bit of wall is OK.",
        "Do NOT include the crosshair, gun, or muzzle flash.",
    ],
    "ammo": [
        "DRAG a tight box around the AMMO NUMBER (e.g. 34/34), then ENTER",
        "Just the digits. Avoid the weapon icon and grenade/gadget icons.",
    ],
    "muzzle": [
        "DRAG a box over the GUN MUZZLE / front sight, then ENTER",
        "Cover where the bright flash appears each shot.",
    ],
    "box": [
        "OPTIONAL: DRAG a box around a HIGH-CONTRAST part of the black crate",
        "Use its labelled corner. Keep it ON the crate - no floor or gun.",
        "Press ENTER to use it, or ESC to skip.",
    ],
}

# Known The Finals magazine sizes (extend as needed).
WEAPON_PRESETS: dict[str, int] = {
    "AKM": 34,
    "Custom": 0,
}


class RecoilGui:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("S4NT0S Recoil Analyser")
        self.root.resizable(False, False)
        self._apply_dark_theme()

        self.video = StringVar()
        self.weapon = StringVar(value="AKM")
        self.magazine = StringVar(value="34")
        self.fov = StringVar(value="81")
        self.fov_axis = StringVar(value="vertical")
        self.distance = StringVar(value="13")
        self.method = StringVar(value="ocr")
        self.outdir = StringVar(value=str(Path("output").resolve()))
        self.track_box = BooleanVar(value=False)
        self.use_audio = BooleanVar(value=True)
        self.show_plot = BooleanVar(value=True)
        self.review = BooleanVar(value=True)  # OCR: ask user about problem frames
        self.status = StringVar(value="Select a video to begin.")

        self._build()

    # ---- theme -----------------------------------------------------------
    def _apply_dark_theme(self) -> None:
        bg, fg, field, acc, active = "#1e1e1e", "#e0e0e0", "#2d2d2d", "#3a3a3a", "#505050"
        self.root.configure(bg=bg)
        # combobox dropdown list (not a ttk-styled widget) needs option_add
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", acc)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure(".", background=bg, foreground=fg, fieldbackground=field,
                        bordercolor=acc, lightcolor=acc, darkcolor=acc, insertcolor=fg)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("Hint.TLabel", background=bg, foreground="#9aa0a6")
        style.configure("Link.TButton", background=bg, foreground="#4ea1ff", borderwidth=0)
        style.map("Link.TButton", background=[("active", bg)], foreground=[("active", "#79bbff")])
        style.configure("TButton", background=acc, foreground=fg, borderwidth=1)
        style.map("TButton", background=[("active", active)])
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TRadiobutton", background=bg, foreground=fg)
        style.map("TRadiobutton", background=[("active", bg)])
        style.configure("TEntry", fieldbackground=field, foreground=fg, insertcolor=fg)
        style.configure("TCombobox", fieldbackground=field, background=acc, foreground=fg,
                        arrowcolor=fg)
        style.map("TCombobox", fieldbackground=[("readonly", field)])

    # ---- layout ----------------------------------------------------------
    def _build(self) -> None:
        f = ttk.Frame(self.root, padding=12)
        f.grid(sticky="nsew")
        row = 0

        def label(text: str) -> None:
            ttk.Label(f, text=text).grid(row=row, column=0, sticky="w", pady=3)

        label("Video file")
        ttk.Entry(f, textvariable=self.video, width=44).grid(row=row, column=1, sticky="we")
        ttk.Button(f, text="Browse...", command=self._browse_video).grid(row=row, column=2, padx=4)
        row += 1

        label("Weapon")
        wcombo = ttk.Combobox(f, textvariable=self.weapon, values=list(WEAPON_PRESETS), width=20)
        wcombo.grid(row=row, column=1, sticky="w")
        wcombo.bind("<<ComboboxSelected>>", self._on_weapon)
        row += 1

        label("Magazine size")
        ttk.Entry(f, textvariable=self.magazine, width=10).grid(row=row, column=1, sticky="w")
        row += 1

        label("FOV (deg)")
        ttk.Entry(f, textvariable=self.fov, width=10).grid(row=row, column=1, sticky="w")
        ttk.Combobox(f, textvariable=self.fov_axis, values=["horizontal", "vertical", "diagonal"],
                     width=12, state="readonly").grid(row=row, column=2, sticky="w")
        row += 1

        label("Wall distance (m)")
        ttk.Entry(f, textvariable=self.distance, width=10).grid(row=row, column=1, sticky="w")
        row += 1

        label("Shot detection")
        mframe = ttk.Frame(f)
        mframe.grid(row=row, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(mframe, text="OCR ammo counter", variable=self.method, value="ocr").pack(side="left")
        ttk.Radiobutton(mframe, text="dumb ammo counter", variable=self.method, value="ammo").pack(side="left", padx=8)
        ttk.Radiobutton(mframe, text="muzzle flash", variable=self.method, value="muzzle").pack(side="left", padx=8)
        row += 1

        opts = ttk.Frame(f)
        opts.grid(row=row, column=0, columnspan=3, sticky="w", pady=4)
        ttk.Checkbutton(opts, text="track black box (extra cross-check)", variable=self.track_box).pack(side="left")
        ttk.Checkbutton(opts, text="audio RPM", variable=self.use_audio).pack(side="left", padx=8)
        ttk.Checkbutton(opts, text="show plot", variable=self.show_plot).pack(side="left")
        ttk.Checkbutton(opts, text="ask me about OCR issues", variable=self.review).pack(side="left", padx=8)
        row += 1

        label("Output folder")
        ttk.Entry(f, textvariable=self.outdir, width=44).grid(row=row, column=1, sticky="we")
        ttk.Button(f, text="Browse...", command=self._browse_outdir).grid(row=row, column=2, padx=4)
        row += 1

        self.run_btn = ttk.Button(f, text="Select regions & analyse", command=self._run)
        self.run_btn.grid(row=row, column=0, columnspan=3, pady=(10, 4), sticky="we")
        row += 1

        ttk.Label(f, textvariable=self.status, wraplength=440, style="Hint.TLabel").grid(
            row=row, column=0, columnspan=3, sticky="w"
        )
        row += 1

        ttk.Separator(f, orient="horizontal").grid(row=row, column=0, columnspan=3,
                                                    sticky="we", pady=(10, 4))
        row += 1

        footer = ttk.Frame(f)
        footer.grid(row=row, column=0, columnspan=3, sticky="we")
        ttk.Label(footer, text=f"© {__author__} - MIT License", style="Hint.TLabel").pack(side="left")
        ttk.Button(footer, text=f"by {__author__} - {__website__.split('//')[-1]}", style="Link.TButton",
                   cursor="hand2", command=lambda: webbrowser.open(__website__)).pack(side="right")

    # ---- handlers --------------------------------------------------------
    def _on_weapon(self, _evt=None) -> None:
        mag = WEAPON_PRESETS.get(self.weapon.get())
        if mag:
            self.magazine.set(str(mag))

    def _browse_video(self) -> None:
        start = "data" if Path("data").is_dir() else "."
        path = filedialog.askopenfilename(
            initialdir=start,
            filetypes=[("Video", "*.mp4 *.mkv *.mov *.avi *.webm"), ("All", "*.*")],
        )
        if path:
            self.video.set(path)
            self._set_status("Video selected. Press 'Select regions & analyse'.")

    def _browse_outdir(self) -> None:
        path = filedialog.askdirectory(initialdir=self.outdir.get() or ".")
        if path:
            self.outdir.set(path)

    def _alive(self) -> bool:
        """True while the main window still exists.

        Analysis runs on the UI thread and, with 'show plot' on, plt.show()
        spins its own event loop; the user can close the main window during
        either. Touching widgets afterwards raises a TclError, so callers guard
        post-blocking widget access on this.
        """
        try:
            return bool(self.root.winfo_exists())
        except Exception:
            return False

    def _set_status(self, text: str) -> None:
        if not self._alive():
            return
        self.status.set(text)
        self.root.update_idletasks()

    def _run(self) -> None:
        try:
            self._do_run()
        except Exception as exc:  # surface any failure to the user
            traceback.print_exc()
            if not self._alive():  # window already closed - nothing to report to
                return
            messagebox.showerror("Recoil Analyser", f"{type(exc).__name__}: {exc}")
            self.run_btn.state(["!disabled"])
            self._set_status("Failed - see error dialog / console.")

    def _do_run(self) -> None:
        video = self.video.get().strip()
        if not video or not Path(video).is_file():
            messagebox.showwarning("Recoil Analyser", "Please select a valid video file.")
            return

        magazine = int(self.magazine.get()) if self.magazine.get().strip().isdigit() else None
        method = self.method.get()

        if method == "ocr":
            missing = missing_ocr_dependencies()
            if missing:
                messagebox.showwarning("Recoil Analyser", ocr_dependency_error_message(missing))
                return

        frame = first_frame(video)
        self._set_status("Draw a box around the WALL TAG in the popup (instructions shown there).")
        tag = select_roi_scaled(frame, "Select WALL TAG", instructions=ROI_HELP["tag"])
        if tag is None:
            self._set_status("Cancelled - a tag ROI is required.")
            return

        ammo = muzzle = box = None
        if method in ("ammo", "ocr"):
            self._set_status("Draw a box around the AMMO COUNTER number in the popup.")
            ammo = select_roi_scaled(frame, "Select AMMO COUNTER", instructions=ROI_HELP["ammo"])
            if ammo is None:
                self._set_status("Cancelled - ammo ROI required for this method.")
                return
        else:
            self._set_status("Draw a box around the MUZZLE / front-sight in the popup.")
            muzzle = select_roi_scaled(frame, "Select MUZZLE", instructions=ROI_HELP["muzzle"])
            if muzzle is None:
                self._set_status("Cancelled - muzzle ROI required for muzzle method.")
                return

        if self.track_box.get():
            self._set_status("Optionally draw a box around the black crate in the popup.")
            box = select_roi_scaled(frame, "Select BLACK BOX (optional)", instructions=ROI_HELP["box"])

        cfg = AnalysisConfig(
            video_path=video,
            tag_roi=tag,
            weapon=self.weapon.get().strip() or "Unknown",
            magazine=magazine,
            shot_method=method,
            ammo_roi=ammo,
            muzzle_roi=muzzle,
            box_roi=box,
            fov_deg=float(self.fov.get()),
            fov_axis=self.fov_axis.get(),
            distance_m=float(self.distance.get()),
            use_audio=self.use_audio.get(),
            progress=self._progress,
            review=self._review_ocr if (method == "ocr" and self.review.get()) else None,
        )

        self.run_btn.state(["disabled"])
        self._set_status("Analysing...")
        result = analyse(cfg)

        stem = Path(video).stem
        weapon = cfg.weapon
        out_json = Path(self.outdir.get()) / f"{stem}_{weapon}.json"
        save_json(result, out_json)
        png = out_json.with_suffix(".png")
        save_plot(result, png, show=self.show_plot.get())

        # show=True ran a blocking plot loop; the user may have closed the main
        # window meanwhile. Bail before touching now-dead widgets (TclError).
        if not self._alive():
            return

        self.run_btn.state(["!disabled"])
        d = result.data
        rpm = d["rpm"]
        ocr = d.get("ocr")
        ocr_lines = ""
        if ocr:
            ocr_lines = (
                f"OCR score min/mean: {ocr['min_score']} / {ocr['mean_score']} "
                f"({ocr['frames_read']}/{ocr['frames_total']} frames read)\n"
            )
            if ocr["shots_match_magazine"] is False:
                ocr_lines += (
                    f"WARNING: {d['shots_detected']} shots != magazine {d['magazine']} "
                    "- check the ammo ROI / magazine.\n"
                )
            if ocr["over_magazine_rejected"]:
                ocr_lines += (
                    f"WARNING: {ocr['over_magazine_rejected']} frame(s) read above the "
                    "magazine and were discarded.\n"
                )
        summary = (
            f"Shots detected: {d['shots_detected']} (magazine {d['magazine']})\n"
            f"RPM (video span): {rpm['video_span']}\n"
            f"RPM (median):     {rpm['video_median']}\n"
            f"RPM (mech. max):  {rpm['mechanical_max']}\n"
            f"RPM (audio):      {rpm['audio']}\n"
            f"Tracking confidence min/mean: "
            f"{d['tracking']['min_confidence']:.3f} / {d['tracking']['mean_confidence']:.3f}\n"
            f"{ocr_lines}\n"
            f"JSON: {out_json}\nPlot: {png}"
        )
        self._set_status(f"Done. {d['shots_detected']} shots, RPM~{rpm['video_span']}.")
        if result.ocr_series is not None:
            self._show_ocr_window(result, d["magazine"])
        messagebox.showinfo("Recoil Analyser - done", summary)

    def _show_ocr_window(self, result, magazine) -> None:
        """Pop a scrollable window listing what the OCR read at each frame."""
        from .ocr import transcript_lines

        lines = transcript_lines(result.ocr_series, result.shot_frames, magazine)
        bg, fg, field = "#1e1e1e", "#e0e0e0", "#2d2d2d"
        win = Toplevel(self.root)
        win.title("OCR readings per frame")
        win.configure(bg=bg)
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(frame, orient="vertical")
        scroll.pack(side="right", fill="y")
        text = Text(
            frame, width=52, height=28, bg=field, fg=fg, insertbackground=fg,
            relief="flat", font=("Consolas", 10), yscrollcommand=scroll.set,
        )
        text.pack(side="left", fill="both", expand=True)
        scroll.config(command=text.yview)
        header = (
            f"{result.data['shots_detected']} shots detected "
            f"(magazine {magazine}).\nOnly frames where the reading changed are shown.\n"
            + "-" * 48 + "\n"
        )
        text.insert("1.0", header + "\n".join(lines))
        text.config(state="disabled")  # read-only

    def _review_ocr(self, problems, crops, readings, texts) -> dict:
        """Modal: show each flagged crop and let the user confirm/correct it.

        Returns {frame_index: corrected_count_or_None}. Runs on the UI thread
        (analysis is synchronous here), so ``wait_window`` blocks until Done.
        """
        import base64

        import cv2

        from .ocr import parse_reading

        bg, fg, field = "#1e1e1e", "#e0e0e0", "#2d2d2d"
        mag = int(self.magazine.get()) if self.magazine.get().strip().isdigit() else None

        win = Toplevel(self.root)
        win.title("Confirm OCR readings")
        win.configure(bg=bg)
        win.transient(self.root)
        win.grab_set()
        ttk.Label(
            win, style="Hint.TLabel", wraplength=540,
            text=(f"{len(problems)} frame(s) need confirming. Type the CURRENT "
                  "ammo number you see in each crop; leave blank if unreadable."),
        ).pack(padx=10, pady=(10, 6))

        container = ttk.Frame(win)
        container.pack(fill="both", expand=True, padx=8)
        canvas = Canvas(container, bg=bg, highlightthickness=0, width=560, height=430)
        sb = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        self._review_imgs = []  # keep PhotoImage refs alive
        entries: dict[int, Entry] = {}
        for f in problems:
            row = ttk.Frame(inner)
            row.pack(fill="x", pady=3, anchor="w")
            disp = cv2.resize(crops[f], None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
            img = PhotoImage(data=base64.b64encode(cv2.imencode(".png", disp)[1].tobytes()))
            self._review_imgs.append(img)
            ttk.Label(row, image=img).pack(side="left", padx=4)
            ttk.Label(row, style="Hint.TLabel", text=f"frame {f}\nOCR: {texts[f]!r}").pack(side="left", padx=6)
            e = Entry(row, width=6, bg=field, fg=fg, insertbackground=fg, justify="center")
            guess = parse_reading(texts[f], mag)
            e.insert(0, "" if guess is None else str(guess))
            e.pack(side="left", padx=6)
            entries[f] = e

        result: dict[int, int | None] = {}

        def done() -> None:
            # parse_reading is forgiving: "0", "0/30" and "30/30" all work;
            # blank/garbage -> None (unreadable).
            for fr, ent in entries.items():
                result[fr] = parse_reading(ent.get(), None)
            win.destroy()

        ttk.Button(win, text="Done", command=done).pack(pady=8)
        if entries:
            next(iter(entries.values())).focus_set()
        win.wait_window()
        return result

    def _progress(self, done: int, total: int) -> None:
        if done % 15 == 0 or done == total:
            pct = f"{100 * done / total:.0f}%" if total else f"{done}"
            self._set_status(f"Analysing... frame {done}/{total} ({pct})")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    RecoilGui().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
