"""Tkinter GUI for compressor.py. Run: python app.py"""
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from compressor import INPUT_EXTENSIONS, LOSSY, OUTPUT_FORMATS, Options, compress

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
except ImportError:  # drag and drop is optional
    DND_FILES, BaseTk = None, tk.Tk


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("Image Compressor")
        self.geometry("900x600")
        self.minsize(760, 480)
        self.files = {}  # tree item id -> Path
        self.events = queue.Queue()
        self.running = False
        self._build()
        self.after(100, self._poll)

    def _build(self):
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        for text, cmd in (("Add files…", self.add_files), ("Add folder…", self.add_folder),
                          ("Select all", self.select_all), ("Remove selected", self.remove_selected),
                          ("Clear", self.clear)):
            ttk.Button(top, text=text, command=cmd).pack(side="left", padx=(0, 6))
        hint = "Drop images or folders on the list. " if DND_FILES else ""
        ttk.Label(top, text=hint + "Shift/Cmd-click to select several.", foreground="gray").pack(side="left", padx=6)

        cols = ("size", "new", "saved", "status")
        self.tree = ttk.Treeview(self, columns=cols, selectmode="extended")
        self.tree.heading("#0", text="File")
        self.tree.column("#0", width=340)
        for c, title, w in zip(cols, ("Original", "Compressed", "Saved", "Status"), (90, 90, 70, 220)):
            self.tree.heading(c, text=title)
            self.tree.column(c, width=w, anchor="e" if c != "status" else "w")
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._update_go())
        for seq in ("<Command-a>", "<Control-a>"):
            self.tree.bind(seq, lambda e: (self.select_all(), "break")[1])
        for seq in ("<Delete>", "<BackSpace>"):
            self.tree.bind(seq, lambda e: self.remove_selected())
        if DND_FILES:
            self.tree.drop_target_register(DND_FILES)
            self.tree.dnd_bind("<<Drop>>", self.on_drop)

        opts = ttk.LabelFrame(self, text="Options", padding=8)
        opts.pack(side="right", fill="y", padx=8, pady=(0, 8))
        scroll.pack(side="right", fill="y", pady=(0, 8))
        self.tree.pack(fill="both", expand=True, padx=(8, 0), pady=(0, 8))

        self.v_fmt = tk.StringVar(value="KEEP")
        self.v_quality = tk.IntVar(value=80)
        self.v_lossless = tk.BooleanVar()
        self.v_w = tk.StringVar(value="0")
        self.v_h = tk.StringVar(value="0")
        self.v_target = tk.StringVar(value="0")
        self.v_strip = tk.BooleanVar(value=True)
        self.v_gray = tk.BooleanVar()
        self.v_skip = tk.BooleanVar(value=True)
        self.v_suffix = tk.StringVar(value="_compressed")
        self.v_out = tk.StringVar()

        r = 0
        def row(label, widget):
            nonlocal r
            ttk.Label(opts, text=label).grid(row=r, column=0, sticky="w", pady=3)
            widget.grid(row=r, column=1, sticky="ew", pady=3)
            r += 1

        row("Output format", ttk.Combobox(opts, textvariable=self.v_fmt, state="readonly", width=14,
                                          values=["KEEP", *OUTPUT_FORMATS]))
        qframe = ttk.Frame(opts)
        self.q_label = ttk.Label(qframe, width=4, text="80")
        ttk.Scale(qframe, from_=1, to=100, variable=self.v_quality,
                  command=lambda v: self.q_label.config(text=str(int(float(v))))).pack(side="left", fill="x", expand=True)
        self.q_label.pack(side="left")
        row("Quality", qframe)
        row("Max width (px)", ttk.Spinbox(opts, textvariable=self.v_w, from_=0, to=100000, increment=100, width=10))
        row("Max height (px)", ttk.Spinbox(opts, textvariable=self.v_h, from_=0, to=100000, increment=100, width=10))
        row("Target size (KB)", ttk.Spinbox(opts, textvariable=self.v_target, from_=0, to=10**6, increment=50, width=10))
        ttk.Label(opts, text="0 = off. Target size overrides quality\n(JPEG, WEBP, AVIF, HEIF, JPEG2000).",
                  foreground="gray").grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        for text, var in (("Lossless (WEBP/AVIF/HEIF/PNG/JP2)", self.v_lossless),
                          ("Strip metadata (EXIF, GPS)", self.v_strip),
                          ("Grayscale", self.v_gray),
                          ("Keep original if not smaller", self.v_skip)):
            ttk.Checkbutton(opts, text=text, variable=var).grid(row=r, column=0, columnspan=2, sticky="w", pady=2)
            r += 1
        row("File suffix", ttk.Entry(opts, textvariable=self.v_suffix, width=14))
        out = ttk.Frame(opts)
        ttk.Entry(out, textvariable=self.v_out, width=14).pack(side="left", fill="x", expand=True)
        ttk.Button(out, text="…", width=2, command=self.pick_out).pack(side="left")
        row("Output folder", out)
        ttk.Label(opts, text="Empty = same folder as source.", foreground="gray").grid(
            row=r, column=0, columnspan=2, sticky="w"); r += 1

        self.progress = ttk.Progressbar(opts, mode="determinate")
        self.progress.grid(row=r, column=0, columnspan=2, sticky="ew", pady=(16, 4)); r += 1
        self.summary = ttk.Label(opts, text="")
        self.summary.grid(row=r, column=0, columnspan=2, sticky="w"); r += 1
        self.go = ttk.Button(opts, text="Compress all", command=self.start)
        self.go.grid(row=r, column=0, columnspan=2, sticky="ew", pady=8)
        opts.columnconfigure(1, weight=1)

    # ---- file list ----
    def _add(self, paths):
        known = set(self.files.values())
        expanded = []
        for p in map(Path, paths):
            expanded += sorted(f for f in p.rglob("*") if f.is_file()) if p.is_dir() else [p]
        for p in expanded:
            if p.suffix.lower() in INPUT_EXTENSIONS and p not in known:
                iid = self.tree.insert("", "end", text=p.name, values=(human(p.stat().st_size), "", "", "pending"))
                self.files[iid] = p
                known.add(p)
        self._update_go()

    def on_drop(self, event):
        self._add(self.tk.splitlist(event.data))  # splitlist handles paths with spaces in {braces}
        return event.action

    def select_all(self):
        self.tree.selection_set(self.tree.get_children())

    def _update_go(self):
        n = len(self.tree.selection())
        self.go.config(text=f"Compress selected ({n})" if n else "Compress all")

    def add_files(self):
        pattern = " ".join("*" + e for e in INPUT_EXTENSIONS)
        self._add(filedialog.askopenfilenames(filetypes=[("Images", pattern), ("All files", "*")]))

    def add_folder(self):
        d = filedialog.askdirectory()
        if d:
            self._add([d])

    def remove_selected(self):
        if not self.running:
            for iid in self.tree.selection():
                self.tree.delete(iid)
                self.files.pop(iid)
            self._update_go()

    def clear(self):
        if not self.running:
            self.tree.delete(*self.tree.get_children())
            self.files.clear()
            self._update_go()

    def pick_out(self):
        d = filedialog.askdirectory()
        if d:
            self.v_out.set(d)

    # ---- compression ----
    def _read_options(self):
        def num(var, name):
            try:
                v = int(var.get() or 0)
            except ValueError:
                raise ValueError(f"{name} must be a whole number")
            if v < 0:
                raise ValueError(f"{name} cannot be negative")
            return v
        return Options(fmt=self.v_fmt.get(), quality=self.v_quality.get(), lossless=self.v_lossless.get(),
                       max_width=num(self.v_w, "Max width"), max_height=num(self.v_h, "Max height"),
                       target_kb=num(self.v_target, "Target size"), strip_metadata=self.v_strip.get(),
                       grayscale=self.v_gray.get(), skip_if_larger=self.v_skip.get(),
                       suffix=self.v_suffix.get(), out_dir=self.v_out.get().strip())

    def start(self):
        if self.running or not self.files:
            return
        try:
            opts = self._read_options()
        except ValueError as e:
            messagebox.showerror("Invalid option", str(e))
            return
        if not opts.suffix and not opts.out_dir:
            messagebox.showerror("Invalid option", "Set a file suffix or an output folder so originals are not overwritten.")
            return
        if opts.target_kb and opts.fmt not in ("KEEP", *LOSSY):
            messagebox.showwarning("Target size", f"Target size is ignored for {opts.fmt}.")
        selected = self.tree.selection()
        jobs = [(i, self.files[i]) for i in selected] if selected else list(self.files.items())
        for iid, _ in jobs:
            self.tree.set(iid, "status", "queued")
        self.running = True
        self.totals = [0, 0]
        self.go.config(state="disabled")
        self.progress.config(maximum=len(jobs), value=0)
        threading.Thread(target=self._worker, args=(jobs, opts), daemon=True).start()

    def _worker(self, jobs, opts):
        for iid, path in jobs:
            try:
                self.events.put(("ok", iid, compress(path, opts)))
            except Exception as e:  # one bad file must not stop the batch
                self.events.put(("err", iid, e))
        self.events.put(("done", None, None))

    def _poll(self):
        while not self.events.empty():
            kind, iid, data = self.events.get()
            if kind == "done":
                self.running = False
                self.go.config(state="normal")
                continue
            self.progress.step(1)
            if kind == "ok":
                saved = 100 * (1 - data.new_size / data.old_size) if data.old_size else 0
                self.tree.item(iid, values=(human(data.old_size), human(data.new_size), f"{saved:.0f}%",
                                            data.note or f"→ {data.dst.name}"))
                self.totals[0] += data.old_size
                self.totals[1] += data.new_size
            else:
                self.tree.set(iid, "status", f"error: {data}")
            self._update_summary()
        self.after(100, self._poll)

    def _update_summary(self):
        old, new = self.totals
        pct = 100 * (1 - new / old) if old else 0
        self.summary.config(text=f"{human(old)} → {human(new)}  (saved {pct:.0f}%)")


if __name__ == "__main__":
    App().mainloop()
