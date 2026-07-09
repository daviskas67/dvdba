#!/usr/bin/env python3
"""
DVDBA Desktop Pro — профессиональный GUI для DVDBC кодека.
"""

import os, sys, time, threading, json, struct, glob, math
from pathlib import Path
from datetime import datetime
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dvdbc.codec import encode_frame, decode_frame
from dvdbc.container import muxer
from dvdbc.quality import psnr, ssim
from dvdbc.cli import rgb_to_yuv_from_rgb

# ── Constants ──────────────────────────────────────────────────────────
APP_NAME = "DVDBA Codec"
VERSION = "1.5.0"
CONFIG_FILE = Path.home() / ".dvdbarc"
COLORS = {
    "bg_dark": "#0d0d1a",
    "bg_card": "#14142a",
    "bg_hover": "#1c1c3a",
    "accent": "#00d4ff",
    "accent2": "#7c4dff",
    "success": "#00e676",
    "warning": "#ffab00",
    "danger": "#ff1744",
    "text": "#e8e8f0",
    "text_muted": "#8888aa",
    "border": "#2a2a4a",
}

# ── Config ──────────────────────────────────────────────────────────────
class Settings:
    def __init__(self):
        self.data = dict(theme="darkly", quality=50, keyframe=30,
                         outdir=str(Path.home() / "Videos"), recent=[])
        self.load()

    def load(self):
        if CONFIG_FILE.exists():
            try:
                d = json.loads(CONFIG_FILE.read_text())
                self.data.update({k: d.get(k, v) for k, v in self.data.items()})
            except:
                pass

    def save(self):
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2, default=str))

    def __getattr__(self, k):
        return self.data.get(k, "")

    def __setattr__(self, k, v):
        if k == "data":
            super().__setattr__(k, v)
        else:
            self.data[k] = v


settings = Settings()


# ── Helpers ─────────────────────────────────────────────────────────────
def fmt_size(b):
    for u in ('B','KB','MB','GB'): return f"{b:.1f} {u}" if b < 1024 else None or (b := b / 1024) is None

def fmt_size(b):
    for u in ('B','KB','MB','GB','TB'):
        if b < 1024: return f"{b:.1f} {u}"
        b /= 1024
    return f"{b:.1f} TB"

def fmt_time(s):
    if s < 60: return f"{s:.1f}s"
    m, s = divmod(s, 60)
    return f"{int(m)}m {s:.0f}s"

def rgba(r, g, b, a=255):
    return f"#{r:02x}{g:02x}{b:02x}"


# ── Custom Widgets ──────────────────────────────────────────────────────
class HeaderBar(ttk.Frame):
    """Modern header with app title and controls."""
    def __init__(self, master, app, **kw):
        super().__init__(master, **kw)
        self.app = app
        self.configure(height=64)
        self.pack_propagate(False)

        # Gradient-like effect via canvas
        self.canvas = ttk.Canvas(self, height=64, highlightthickness=0)
        self.canvas.pack(fill="x")
        self.canvas.create_rectangle(0, 0, 2000, 64,
                                     fill="#14142a", outline="")

        # Accent line
        self.canvas.create_rectangle(0, 60, 2000, 64,
                                     fill="#00d4ff", outline="")

        # App icon (text-based)
        self.canvas.create_text(28, 26, text="DVDBA", anchor="w",
                                fill="#00d4ff", font=("Segoe UI", 20, "bold"))
        self.canvas.create_text(120, 32, text="PRO", anchor="w",
                                fill="#7c4dff", font=("Segoe UI", 12, "bold"))
        self.canvas.create_text(28, 48, text="Video Codec Studio",
                                anchor="w", fill="#6666aa",
                                font=("Segoe UI", 9))

        # Theme selector
        themes_frame = ttk.Frame(self)
        themes_frame.place(relx=1.0, x=-80, y=18, anchor="ne")
        self.theme_var = ttk.StringVar(value=settings.theme)
        themes = {"darkly": "🌙", "superhero": "🦸", "cyborg": "🤖",
                  "vapor": "🌊", "solar": "☀️"}
        for tn, emoji in themes.items():
            btn = ttk.Button(themes_frame, text=emoji, bootstyle="secondary-link",
                             command=lambda t=tn: app.set_theme(t), width=3)
            btn.pack(side="left", padx=1)

        # Version
        self.canvas.create_text(2000, 56, text=f"v{VERSION}",
                                anchor="se", fill="#4444aa",
                                font=("Segoe UI", 8))


class CardFrame(ttk.Frame):
    """Card-style container with rounded look."""
    def __init__(self, master, title="", **kw):
        super().__init__(master, **kw)
        self.configure(padding=0)
        self.title = title

        # Shadow effect
        self.shadow = ttk.Frame(self, height=2)
        self.shadow.pack(fill="x", padx=4)
        self.shadow.configure(style="darkly.Inverse.TFrame")

        self.inner = ttk.Frame(self, padding=14)
        self.inner.pack(fill="both", expand=True)

        if title:
            lbl = ttk.Label(self.inner, text=title,
                            font=("Segoe UI", 11, "bold"),
                            bootstyle="inverse-secondary")
            lbl.pack(anchor="w", pady=(0, 10))


class StatCard(ttk.Frame):
    """Small metric display card."""
    def __init__(self, master, label="", value="", accent="#00d4ff", **kw):
        super().__init__(master, **kw)
        self.configure(padding=10)

        self.label_w = ttk.Label(self, text=label,
                                 font=("Segoe UI", 8),
                                 bootstyle="secondary")
        self.label_w.pack(anchor="w")

        self.value_w = ttk.Label(self, text=value,
                                 font=("Segoe UI", 16, "bold"),
                                 foreground=accent)
        self.value_w.pack(anchor="w")

    def set(self, value):
        self.value_w.config(text=str(value))


class DropZone(ttk.Label):
    """Drag & drop zone for files."""
    def __init__(self, master, text="Drop video here", **kw):
        super().__init__(master, text=text, **kw)
        self.configure(anchor="center", padding=30,
                       font=("Segoe UI", 12),
                       bootstyle="secondary-inverse")


class AnimatedButton(ttk.Button):
    """Button with loading state."""
    def __init__(self, master, **kw):
        self._loading = False
        self._orig_text = kw.get("text", "")
        super().__init__(master, **kw)

    def set_loading(self, loading=True):
        if loading:
            self._loading = True
            self.config(text="⏳ Processing...", state="disabled")
        else:
            self._loading = False
            self.config(text=self._orig_text, state="normal")


# ── Tab: Encode ─────────────────────────────────────────────────────────
class EncodeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.input_path = None
        self.running = False
        self._cancel_flag = False
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        # ── Left Panel ──
        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="nsew")

        # Source section
        src_card = CardFrame(left, title="📁 Source")
        src_card.pack(fill="x", pady=(0, 8))

        btn_row = ttk.Frame(src_card.inner)
        btn_row.pack(fill="x", pady=(0, 5))
        self.browse_btn = ttk.Button(btn_row, text="Browse Video",
                                     bootstyle="info-outline",
                                     command=self._browse)
        self.browse_btn.pack(side="left", padx=(0, 5))
        self.clear_btn = ttk.Button(btn_row, text="✕", width=3,
                                    bootstyle="secondary-outline",
                                    command=self._clear)
        self.clear_btn.pack(side="left")

        self.file_label = ttk.Label(src_card.inner, text="No file selected",
                                    font=("Segoe UI", 9),
                                    bootstyle="secondary")
        self.file_label.pack(anchor="w")

        self.file_info = ttk.Label(src_card.inner, text="",
                                   font=("Segoe UI", 8),
                                   bootstyle="secondary")
        self.file_info.pack(anchor="w")

        # Preview + frame nav
        self.preview_frame = ttk.Frame(src_card.inner)
        self.preview_frame.pack(fill="x", pady=(8, 0))

        self.preview_canvas = ttk.Canvas(self.preview_frame,
                                         width=260, height=160,
                                         highlightthickness=1,
                                         highlightbackground="#2a2a4a",
                                         bg="#0d0d1a")
        self.preview_canvas.pack()
        self._draw_placeholder(self.preview_canvas, "Preview")

        nav_row = ttk.Frame(self.preview_frame)
        nav_row.pack(fill="x", pady=(4, 0))
        self.frame_pos = ttk.Scale(nav_row, from_=0, to=100, value=0,
                                    state="disabled")
        self.frame_pos.pack(fill="x", side="left", expand=True, padx=(0, 5))
        self.frame_label = ttk.Label(nav_row, text="0/0",
                                     font=("Segoe UI", 8))
        self.frame_label.pack(side="right")

        # Settings section
        settings_card = CardFrame(left, title="⚙️ Settings")
        settings_card.pack(fill="x")

        # Quality
        q_row = ttk.Frame(settings_card.inner)
        q_row.pack(fill="x", pady=3)
        ttk.Label(q_row, text="Quality", font=("Segoe UI", 9)).pack(side="left")
        self.quality_val = ttk.Label(q_row, text=str(settings.quality),
                                     font=("Segoe UI", 9, "bold"),
                                     foreground="#00d4ff")
        self.quality_val.pack(side="right")

        self.quality_slider = ttk.Scale(settings_card.inner, from_=1, to=100,
                                         value=settings.quality,
                                         command=self._on_q)
        self.quality_slider.pack(fill="x", pady=(0, 8))

        # Quality presets
        presets = ttk.Frame(settings_card.inner)
        presets.pack(fill="x", pady=(0, 8))
        for label, q in [("Fast", 10), ("Good", 30), ("High", 50), ("Pro", 80), ("Max", 100)]:
            btn = ttk.Button(presets, text=label, bootstyle="secondary-outline",
                             width=5, command=lambda v=q: self._set_q(v))
            btn.pack(side="left", padx=1)

        # Keyframe
        kf_row = ttk.Frame(settings_card.inner)
        kf_row.pack(fill="x", pady=3)
        ttk.Label(kf_row, text="Keyframe interval",
                  font=("Segoe UI", 9)).pack(side="left")
        self.kf_var = ttk.IntVar(value=settings.keyframe)
        self.kf_spin = ttk.Spinbox(kf_row, from_=1, to=300,
                                    textvariable=self.kf_var, width=5)
        self.kf_spin.pack(side="right")

        # Encode button
        self.encode_btn = ttk.Button(settings_card.inner,
                                      text="▶  Encode Video",
                                      bootstyle="success",
                                      command=self._encode,
                                      padding=(20, 10))
        self.encode_btn.pack(fill="x", pady=(10, 0))

        # Cancel button
        self.cancel_btn = ttk.Button(settings_card.inner,
                                      text="■ Cancel",
                                      bootstyle="secondary",
                                      state="disabled",
                                      command=self._cancel)
        self.cancel_btn.pack(fill="x", pady=(4, 0))

        # ── Right Panel ──
        right = ttk.Frame(self, padding=10)
        right.grid(row=0, column=1, sticky="nsew")

        # Stats dashboard
        stats_card = CardFrame(right, title="📊 Dashboard")
        stats_card.pack(fill="x", pady=(0, 8))

        grid = ttk.Frame(stats_card.inner)
        grid.pack(fill="x")
        grid.columnconfigure((0, 1, 2), weight=1)

        self.stat_frames = StatCard(grid, label="Frames", value="0")
        self.stat_frames.grid(row=0, column=0, padx=2, sticky="ew")
        self.stat_size = StatCard(grid, label="Output", value="—", accent="#7c4dff")
        self.stat_size.grid(row=0, column=1, padx=2, sticky="ew")
        self.stat_speed = StatCard(grid, label="Speed", value="—", accent="#00e676")
        self.stat_speed.grid(row=0, column=2, padx=2, sticky="ew")

        # Progress
        progress_card = CardFrame(right, title="⏳ Progress")
        progress_card.pack(fill="x", pady=(0, 8))

        self.progress = ttk.Progressbar(progress_card.inner,
                                         mode="determinate", value=0)
        self.progress.pack(fill="x", pady=(0, 5))

        self.progress_label = ttk.Label(progress_card.inner,
                                         text="Ready",
                                         font=("Segoe UI", 9))
        self.progress_label.pack(anchor="w")

        self.progress_detail = ttk.Label(progress_card.inner,
                                          text="",
                                          font=("Segoe UI", 8),
                                          bootstyle="secondary")
        self.progress_detail.pack(anchor="w")

        # Output card
        out_card = CardFrame(right, title="💾 Output")
        out_card.pack(fill="x")

        self.out_label = ttk.Label(out_card.inner, text="",
                                   font=("Segoe UI", 9))
        self.out_label.pack(anchor="w")

        self.open_btn = ttk.Button(out_card.inner, text="Open Output Folder",
                                    bootstyle="info-link",
                                    state="disabled",
                                    command=self._open_outdir)
        self.open_btn.pack(anchor="w", pady=(4, 0))

        # Status bar
        status_bar = ttk.Frame(self)
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10)
        self.status_icon = ttk.Label(status_bar, text="●",
                                      font=("Segoe UI", 8),
                                      foreground="#444")
        self.status_icon.pack(side="left", padx=(0, 5))
        self.status_text = ttk.Label(status_bar, text="Ready",
                                      font=("Segoe UI", 9),
                                      bootstyle="secondary")
        self.status_text.pack(side="left")

        self.last_output = None

    def _draw_placeholder(self, canvas, text):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 260, 160, fill="#0d0d1a", outline="")
        canvas.create_text(130, 78, text=text, fill="#444",
                           font=("Segoe UI", 12))

    def _on_q(self, *a):
        v = int(self.quality_slider.get())
        self.quality_val.config(text=str(v))

    def _set_q(self, v):
        self.quality_slider.set(v)
        self.quality_val.config(text=str(v))

    def _browse(self):
        path = ttk.filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video", "*.mp4 *.avi *.mov *.mkv *.webm"),
                       ("All", "*.*")]
        )
        if path:
            self._load_file(path)

    def _clear(self):
        self.input_path = None
        self.file_label.config(text="No file selected")
        self.file_info.config(text="")
        self._draw_placeholder(self.preview_canvas, "Preview")
        self.frame_pos.config(state="disabled", to=100, value=0)
        self.frame_label.config(text="0/0")

    def _load_file(self, path):
        self.input_path = path
        self.file_label.config(text=os.path.basename(path))
        if cv2:
            cap = cv2.VideoCapture(path)
            w, h = int(cap.get(3)), int(cap.get(4))
            fps = cap.get(5)
            nf = int(cap.get(7))
            sz = os.path.getsize(path)
            self.file_info.config(
                text=f"{w}×{h}  •  {fps:.0f} fps  •  {nf} frames  •  {fmt_size(sz)}"
            )
            ret, frame = cap.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._show_preview(rgb)
                self.frame_pos.config(state="normal", to=max(nf-1, 1), value=0)
                self.frame_label.config(text=f"0/{nf}")
            cap.release()

            # Add to recent
            recent = settings.recent
            if path in recent:
                recent.remove(path)
            recent.insert(0, path)
            settings.recent = recent[:10]
            settings.save()

    def _show_preview(self, rgb):
        h, w = rgb.shape[:2]
        scale = min(260 / w, 160 / h)
        nw, nh = int(w * scale), int(h * scale)
        img = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        c = self.preview_canvas
        c.delete("all")
        c.create_rectangle(0, 0, 260, 160, fill="#0d0d1a", outline="")
        c.create_image((260 - nw)//2, (160 - nh)//2, anchor="nw",
                       image=self._photo)

    def _encode(self):
        if not self.input_path:
            Messagebox.show_error("Select a video file first.", "Error")
            return
        if self.running:
            return

        out_path = ttk.filedialog.asksaveasfilename(
            defaultextension=".dvdbc",
            filetypes=[("DVDBC", "*.dvdbc"), ("All", "*.*")]
        )
        if not out_path:
            return

        self.running = True
        self._cancel_flag = False
        self.encode_btn.config(state="disabled", text="⏳ Encoding...")
        self.cancel_btn.config(state="normal")
        self.status_icon.config(foreground="#ffab00")
        self.status_text.config(text="Encoding...")
        self.open_btn.config(state="disabled")

        quality = int(self.quality_slider.get())
        keyframe = self.kf_var.get()
        settings.quality = quality
        settings.keyframe = keyframe
        settings.save()

        t = threading.Thread(target=self._encode_thread,
                             args=(self.input_path, out_path, quality, keyframe),
                             daemon=True)
        t.start()

    def _cancel(self):
        self._cancel_flag = True
        self.cancel_btn.config(state="disabled")
        self.status_text.config(text="Cancelling...")

    def _encode_thread(self, in_path, out_path, quality, keyframe):
        try:
            cap = cv2.VideoCapture(in_path)
            w = int(cap.get(3)); h = int(cap.get(4))
            fps = cap.get(5); total = int(cap.get(7))
            if total <= 0: total = 100

            header = muxer.mux_header(w, h, fps, total, float(quality), keyframe)
            frames_data = []
            ref_y = None
            start = time.time()

            for i in range(total):
                if self._cancel_flag:
                    break
                ret, frame = cap.read()
                if not ret: break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                is_key = i % keyframe == 0
                fd, recon_y, _ = encode_frame(rgb, float(quality),
                                               None if is_key else ref_y)
                ref_y = recon_y
                frames_data.append(fd)

                el = time.time() - start
                pct = int((i + 1) / total * 100)
                fps_p = (i + 1) / el if el > 0 else 0
                self.after(0, self._update_progress, pct,
                           f"Frame {i+1}/{total} • {fps_p:.1f} fps")

            cap.release()

            if self._cancel_flag:
                self.after(0, self._encode_cancelled)
                return

            out_dir = os.path.dirname(out_path)
            os.makedirs(out_dir, exist_ok=True)
            with open(out_path, "wb") as f:
                f.write(header)
                for fd in frames_data:
                    f.write(fd)

            el = time.time() - start
            sz = os.path.getsize(out_path)
            self.last_output = out_path
            self.after(0, self._encode_done, len(frames_data), el, sz)
        except Exception as e:
            self.after(0, self._encode_error, str(e))

    def _update_progress(self, pct, status):
        self.progress["value"] = pct
        self.progress_label.config(text=status)
        self.stat_frames.set(str(pct) + "%")

    def _encode_done(self, nframes, elapsed, size):
        self.running = False
        self.encode_btn.config(state="normal", text="▶  Encode Video")
        self.cancel_btn.config(state="disabled")
        self.progress["value"] = 100
        self.progress_label.config(text="✅ Complete!")
        self.progress_detail.config(
            text=f"{nframes} frames • {fmt_time(elapsed)} • {nframes/elapsed:.1f} fps"
        )
        self.stat_frames.set(str(nframes))
        self.stat_size.set(fmt_size(size))
        self.stat_speed.set(f"{nframes/elapsed:.1f} fps")
        self.out_label.config(text=f"📁 {os.path.basename(self.last_output)}")
        self.open_btn.config(state="normal")
        self.status_icon.config(foreground="#00e676")
        self.status_text.config(text="Encoding complete")
        Messagebox.show_info(
            f"✅ Encoding complete!\n\n"
            f"Frames: {nframes}\n"
            f"Output: {fmt_size(size)}\n"
            f"Speed: {nframes/elapsed:.1f} fps\n"
            f"Time: {fmt_time(elapsed)}",
            "Success"
        )

    def _encode_cancelled(self):
        self.running = False
        self.encode_btn.config(state="normal", text="▶  Encode Video")
        self.cancel_btn.config(state="disabled")
        self.progress_label.config(text="⛔ Cancelled")
        self.status_icon.config(foreground="#ff1744")
        self.status_text.config(text="Cancelled")

    def _encode_error(self, msg):
        self.running = False
        self.encode_btn.config(state="normal", text="▶  Encode Video")
        self.cancel_btn.config(state="disabled")
        self.progress_label.config(text="❌ Error")
        self.status_icon.config(foreground="#ff1744")
        self.status_text.config(text="Error")
        Messagebox.show_error(msg, "Error")

    def _open_outdir(self):
        if self.last_output:
            os.startfile(os.path.dirname(self.last_output))


# ── Tab: Decode ─────────────────────────────────────────────────────────
class DecodeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.running = False
        self._cancel_flag = False
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        left = ttk.Frame(self, padding=10)
        left.grid(row=0, column=0, sticky="nsew")

        src_card = CardFrame(left, title="📂 DVDBC File")
        src_card.pack(fill="x", pady=(0, 8))

        self.browse_btn = ttk.Button(src_card.inner, text="Open DVDBC File",
                                      bootstyle="info-outline",
                                      command=self._browse)
        self.browse_btn.pack(fill="x", pady=(0, 5))

        self.file_label = ttk.Label(src_card.inner, text="No file selected",
                                    font=("Segoe UI", 9),
                                    bootstyle="secondary")
        self.file_label.pack(anchor="w")

        self.file_info = ttk.Label(src_card.inner, text="",
                                   font=("Segoe UI", 8),
                                   bootstyle="secondary")
        self.file_info.pack(anchor="w")

        info_card = CardFrame(left, title="ℹ️ File Info")
        info_card.pack(fill="x", pady=(0, 8))

        self.meta_text = ttk.Label(info_card.inner, text="",
                                    font=("Segoe UI", 9),
                                    bootstyle="secondary")
        self.meta_text.pack(anchor="w")

        action_card = CardFrame(left, title="▶ Decode")
        action_card.pack(fill="x")

        self.decode_btn = ttk.Button(action_card.inner, text="▶  Decode to MP4",
                                      bootstyle="success",
                                      command=self._decode,
                                      padding=(20, 10))
        self.decode_btn.pack(fill="x", pady=(0, 5))

        self.cancel_btn = ttk.Button(action_card.inner, text="■ Cancel",
                                      bootstyle="secondary",
                                      state="disabled",
                                      command=self._cancel)
        self.cancel_btn.pack(fill="x")

        # Right
        right = ttk.Frame(self, padding=10)
        right.grid(row=0, column=1, sticky="nsew")

        preview_card = CardFrame(right, title="🖼 Preview")
        preview_card.pack(fill="both", expand=True, pady=(0, 8))

        self.preview_canvas = ttk.Canvas(preview_card.inner,
                                          width=380, height=240,
                                          highlightthickness=1,
                                          highlightbackground="#2a2a4a",
                                          bg="#0d0d1a")
        self.preview_canvas.pack()
        self._placeholder(self.preview_canvas, "Decoded Preview")

        progress_card = CardFrame(right, title="⏳ Progress")
        progress_card.pack(fill="x")

        self.progress = ttk.Progressbar(progress_card.inner,
                                         mode="determinate", value=0)
        self.progress.pack(fill="x", pady=(0, 5))

        self.status_text = ttk.Label(progress_card.inner, text="Ready",
                                      font=("Segoe UI", 9))
        self.status_text.pack(anchor="w")

        self.result_text = ttk.Label(progress_card.inner, text="",
                                      font=("Segoe UI", 8),
                                      bootstyle="secondary")
        self.result_text.pack(anchor="w")

    def _placeholder(self, canvas, text):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 380, 240, fill="#0d0d1a", outline="")
        canvas.create_text(190, 118, text=text, fill="#444",
                           font=("Segoe UI", 14))

    def _browse(self):
        path = ttk.filedialog.askopenfilename(
            title="Select DVDBC File",
            filetypes=[("DVDBC", "*.dvdbc"), ("All", "*.*")]
        )
        if path:
            self.input_path = path
            self.file_label.config(text=os.path.basename(path))
            with open(path, "rb") as f:
                hdr = f.read(muxer.HEADER_SIZE)
            info = muxer.parse_header(hdr)
            sz = os.path.getsize(path)
            self.file_info.config(text=fmt_size(sz))
            self.meta_text.config(
                text=f"Resolution: {info['width']}×{info['height']}\n"
                     f"FPS: {info['fps']:.0f}  •  Frames: {info['frame_count']}\n"
                     f"Quality: {info['quality']}  •  Size: {fmt_size(sz)}"
            )

    def _decode(self):
        if not hasattr(self, 'input_path'):
            Messagebox.show_error("Select a DVDBC file first.", "Error")
            return

        out_path = ttk.filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4"), ("All", "*.*")]
        )
        if not out_path:
            return

        self.running = True
        self._cancel_flag = False
        self.decode_btn.config(state="disabled", text="⏳ Decoding...")
        self.cancel_btn.config(state="normal")

        t = threading.Thread(target=self._decode_thread,
                             args=(self.input_path, out_path), daemon=True)
        t.start()

    def _cancel(self):
        self._cancel_flag = True
        self.cancel_btn.config(state="disabled")

    def _decode_thread(self, in_path, out_path):
        try:
            with open(in_path, "rb") as f:
                data = f.read()
            info = muxer.parse_header(data)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(out_path, fourcc, info['fps'],
                                  (info['width'], info['height']))
            ref_y = None
            offset = muxer.HEADER_SIZE
            idx, total = 0, info['frame_count']
            start = time.time()

            while offset < len(data) and not self._cancel_flag:
                rem = data[offset:]
                fsize = int.from_bytes(rem[1:5], 'big')
                rgb = decode_frame(rem[:5+fsize], info['width'], info['height'],
                                   info['quality'], ref_y)
                yuv = rgb_to_yuv_from_rgb(rgb)
                ref_y = yuv[..., 0].astype(np.uint8)
                out.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                offset += 5 + fsize
                idx += 1

                if idx % 5 == 0 or idx == total:
                    pct = int(idx / total * 100)
                    self.after(0, self._update, pct, f"Frame {idx}/{total}")

                if idx == 1:
                    self.after(0, self._show_decoded, rgb)

            out.release()
            el = time.time() - start
            if self._cancel_flag:
                self.after(0, self._decode_cancelled)
            else:
                self.after(0, self._decode_done, idx, el)
        except Exception as e:
            self.after(0, self._decode_error, str(e))

    def _update(self, pct, txt):
        self.progress["value"] = pct
        self.status_text.config(text=txt)

    def _show_decoded(self, rgb):
        h, w = rgb.shape[:2]
        scale = min(380 / w, 240 / h)
        nw, nh = int(w * scale), int(h * scale)
        img = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        c = self.preview_canvas
        c.delete("all")
        c.create_rectangle(0, 0, 380, 240, fill="#0d0d1a", outline="")
        c.create_image((380 - nw)//2, (240 - nh)//2, anchor="nw",
                       image=self._photo)

    def _decode_done(self, nframes, elapsed):
        self.running = False
        self.decode_btn.config(state="normal", text="▶  Decode to MP4")
        self.cancel_btn.config(state="disabled")
        self.progress["value"] = 100
        self.status_text.config(text="✅ Complete!")
        self.result_text.config(
            text=f"{nframes} frames • {fmt_time(elapsed)} • {nframes/elapsed:.1f} fps"
        )

    def _decode_cancelled(self):
        self.running = False
        self.decode_btn.config(state="normal", text="▶  Decode to MP4")
        self.cancel_btn.config(state="disabled")
        self.status_text.config(text="⛔ Cancelled")

    def _decode_error(self, msg):
        self.running = False
        self.decode_btn.config(state="normal", text="▶  Decode to MP4")
        self.cancel_btn.config(state="disabled")
        self.status_text.config(text="❌ Error")
        Messagebox.show_error(msg, "Error")


# ── Tab: Compare ────────────────────────────────────────────────────────
class CompareTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._build_ui()

    def _build_ui(self):
        self.columnconfigure((0, 1), weight=1)
        self.rowconfigure(1, weight=1)

        # Top bar
        top = ttk.Frame(self, padding=10)
        top.grid(row=0, column=0, columnspan=2, sticky="ew")

        ttk.Label(top, text="📐 Quality Comparison",
                  font=("Segoe UI", 14, "bold")).pack(side="left")

        self.compare_btn = ttk.Button(top, text="▶  Compare",
                                       bootstyle="primary",
                                       command=self._compare,
                                       padding=(15, 8))
        self.compare_btn.pack(side="right")

        # Original side
        left = ttk.LabelFrame(self, text="  Original  ", padding=8)
        left.grid(row=1, column=0, sticky="nsew", padx=5, pady=(0, 5))

        self.orig_btn = ttk.Button(left, text="Browse Original",
                                    bootstyle="info-outline",
                                    command=self._browse_orig)
        self.orig_btn.pack(fill="x", pady=(0, 5))

        self.orig_label = ttk.Label(left, text="No file",
                                    bootstyle="secondary",
                                    font=("Segoe UI", 9))
        self.orig_label.pack(anchor="w")

        self.orig_canvas = ttk.Canvas(left, width=300, height=200,
                                       highlightthickness=1,
                                       highlightbackground="#2a2a4a",
                                       bg="#0d0d1a")
        self.orig_canvas.pack()
        self._placeholder(self.orig_canvas, "Original")

        self.orig_stats = ttk.Label(left, text="",
                                    bootstyle="secondary",
                                    font=("Segoe UI", 8))
        self.orig_stats.pack(anchor="w", pady=(4, 0))

        # Compressed side
        right = ttk.LabelFrame(self, text="  DVDBC Decoded  ", padding=8)
        right.grid(row=1, column=1, sticky="nsew", padx=5, pady=(0, 5))

        self.comp_btn = ttk.Button(right, text="Browse DVDBC",
                                    bootstyle="info-outline",
                                    command=self._browse_comp)
        self.comp_btn.pack(fill="x", pady=(0, 5))

        self.comp_label = ttk.Label(right, text="No file",
                                     bootstyle="secondary",
                                     font=("Segoe UI", 9))
        self.comp_label.pack(anchor="w")

        self.comp_canvas = ttk.Canvas(right, width=300, height=200,
                                       highlightthickness=1,
                                       highlightbackground="#2a2a4a",
                                       bg="#0d0d1a")
        self.comp_canvas.pack()
        self._placeholder(self.comp_canvas, "DVDBC Decoded")

        self.comp_stats = ttk.Label(right, text="",
                                    bootstyle="secondary",
                                    font=("Segoe UI", 8))
        self.comp_stats.pack(anchor="w", pady=(4, 0))

        # Results bar
        results = ttk.Frame(self, padding=10)
        results.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.result_frame = ttk.Frame(results)
        self.result_frame.pack(fill="x")

        self.psnr_label = ttk.Label(self.result_frame, text="",
                                     font=("Segoe UI", 16, "bold"))
        self.psnr_label.pack(side="left", padx=10)

        self.ssim_label = ttk.Label(self.result_frame, text="",
                                     font=("Segoe UI", 16, "bold"))
        self.ssim_label.pack(side="left", padx=10)

        self.ratio_label = ttk.Label(self.result_frame, text="",
                                      font=("Segoe UI", 14),
                                      bootstyle="secondary")
        self.ratio_label.pack(side="left", padx=10)

    def _placeholder(self, canvas, text):
        canvas.delete("all")
        canvas.create_rectangle(0, 0, 300, 200, fill="#0d0d1a", outline="")
        canvas.create_text(150, 98, text=text, fill="#444",
                           font=("Segoe UI", 14))

    def _show_image(self, canvas, rgb, w=300, h=200):
        ih, iw = rgb.shape[:2]
        scale = min(w / iw, h / ih)
        nw, nh = int(iw * scale), int(ih * scale)
        img = Image.fromarray(rgb).resize((nw, nh), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        canvas.delete("all")
        canvas.create_rectangle(0, 0, w, h, fill="#0d0d1a", outline="")
        canvas.create_image((w - nw)//2, (h - nh)//2, anchor="nw",
                            image=photo)
        return photo

    def _browse_orig(self):
        p = ttk.filedialog.askopenfilename(title="Original Video",
                                            filetypes=[("Video", "*.mp4 *.avi *.mov"), ("*", "*.*")])
        if p:
            self.orig_path = p
            self.orig_label.config(text=os.path.basename(p))
            cap = cv2.VideoCapture(p)
            ret, frame = cap.read()
            if ret:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                self._orig_photo = self._show_image(self.orig_canvas, rgb)
                self.orig_stats.config(text=fmt_size(os.path.getsize(p)))
            cap.release()

    def _browse_comp(self):
        p = ttk.filedialog.askopenfilename(title="DVDBC File",
                                            filetypes=[("DVDBC", "*.dvdbc"), ("*", "*.*")])
        if p:
            self.comp_path = p
            self.comp_label.config(text=os.path.basename(p))
            with open(p, "rb") as f:
                hdr = f.read(muxer.HEADER_SIZE)
            info = muxer.parse_header(hdr)
            self.comp_stats.config(text=fmt_size(os.path.getsize(p)))

    def _compare(self):
        if not (hasattr(self, 'orig_path') and hasattr(self, 'comp_path')):
            Messagebox.show_error("Select both files.", "Error")
            return
        self.compare_btn.config(state="disabled", text="⏳ Comparing...")
        t = threading.Thread(target=self._compare_thread, daemon=True)
        t.start()

    def _compare_thread(self):
        try:
            with open(self.comp_path, "rb") as f:
                comp = f.read()
            info = muxer.parse_header(comp)
            cap = cv2.VideoCapture(self.orig_path)

            psnr_vals, ssim_vals = [], []
            ref_y, offset = None, muxer.HEADER_SIZE
            idx = 0

            while offset < len(comp):
                ret, frame = cap.read()
                if not ret: break
                orig_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rem = comp[offset:]
                fsize = int.from_bytes(rem[1:5], 'big')

                try:
                    dec_rgb = decode_frame(rem[:5+fsize], info['width'],
                                           info['height'], info['quality'], ref_y)
                except:
                    break

                yuv = rgb_to_yuv_from_rgb(dec_rgb)
                ref_y = yuv[..., 0].astype(np.uint8)
                psnr_vals.append(psnr(orig_rgb, dec_rgb))
                ssim_vals.append(ssim(orig_rgb, dec_rgb))
                offset += 5 + fsize
                idx += 1

                if idx == 1:
                    orig_p = self._show_image(self.orig_canvas, orig_rgb)
                    comp_p = self._show_image(self.comp_canvas, dec_rgb)
                    self._orig_photo = orig_p
                    self._comp_photo = comp_p

            cap.release()

            if psnr_vals:
                avg_p = np.mean(psnr_vals)
                avg_s = np.mean(ssim_vals)
                orig_sz = os.path.getsize(self.orig_path)
                comp_sz = os.path.getsize(self.comp_path)
                ratio = orig_sz / comp_sz if comp_sz > 0 else 0
                self.after(0, self._show_results, avg_p, avg_s, ratio, orig_sz, comp_sz, idx)
            else:
                self.after(0, self._comp_error, "No frames compared")
        except Exception as e:
            self.after(0, self._comp_error, str(e))

    def _show_results(self, psnr_v, ssim_v, ratio, orig_sz, comp_sz, n):
        self.compare_btn.config(state="normal", text="▶  Compare")
        color = "#00e676" if psnr_v > 35 else "#ffab00" if psnr_v > 25 else "#ff1744"
        self.psnr_label.config(
            text=f"📊 PSNR  {psnr_v:.2f} dB",
            foreground=color
        )
        self.ssim_label.config(
            text=f"🎯 SSIM  {ssim_v:.4f}",
            foreground="#00d4ff"
        )
        self.ratio_label.config(
            text=f"📦 {fmt_size(orig_sz)} → {fmt_size(comp_sz)}  ({ratio:.2f}×)"
        )
        self.comp_stats.config(
            text=f"{fmt_size(comp_sz)}  |  {n} frames compared"
        )

    def _comp_error(self, msg):
        self.compare_btn.config(state="normal", text="▶  Compare")
        self.psnr_label.config(text=f"Error: {msg}", foreground="#ff1744")


# ── Main Application ────────────────────────────────────────────────────
class App(ttk.Window):
    def __init__(self):
        super().__init__(title=f"{APP_NAME} v{VERSION}",
                         themename=settings.theme,
                         size=(1100, 740),
                         minsize=(900, 640))
        self.set_icon()
        self._build_ui()
        self._setup_bindings()

    def set_icon(self):
        try:
            icon = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(icon)
            # Glowing circle
            for r in range(28, 20, -2):
                a = int(50 * (1 - (28-r)/8))
                draw.ellipse([4-r, 4-r, 60+r, 60+r],
                             fill=(0, 212, 255, a))
            draw.ellipse([6, 6, 58, 58], fill="#00d4ff")
            draw.text((16, 12), "D", fill="#0d0d1a",
                      font=ImageFont.truetype("segoeui.ttf", 32))
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            icon.save(tmp.name)
            self.iconphoto(True, ImageTk.PhotoImage(file=tmp.name))
        except:
            pass

    def set_theme(self, name):
        settings.theme = name
        settings.save()
        self.style.theme_use(name)

    def _build_ui(self):
        # Header
        self.header = HeaderBar(self, self)
        self.header.pack(fill="x")

        # Notebook
        notebook_frame = ttk.Frame(self)
        notebook_frame.pack(fill="both", expand=True, padx=2, pady=(0, 2))

        style = ttk.Style()
        style.configure("TNotebook", background="#0d0d1a")
        style.configure("TNotebook.Tab",
                       font=("Segoe UI", 10, "bold"),
                       padding=(16, 8))

        self.notebook = ttk.Notebook(notebook_frame)
        self.notebook.pack(fill="both", expand=True)

        self.encode_tab = EncodeTab(self.notebook, self)
        self.decode_tab = DecodeTab(self.notebook, self)
        self.compare_tab = CompareTab(self.notebook, self)

        self.notebook.add(self.encode_tab, text="🎬  Encode")
        self.notebook.add(self.decode_tab, text="📂  Decode")
        self.notebook.add(self.compare_tab, text="📊  Compare")

        # Recent files (Encode tab)
        if settings.recent:
            recent_frame = ttk.Frame(self, padding=(10, 0, 10, 4))
            recent_frame.pack(fill="x")
            ttk.Label(recent_frame, text="Recent:",
                      font=("Segoe UI", 8),
                      bootstyle="secondary").pack(side="left")
            for p in settings.recent[:5]:
                name = os.path.basename(p)
                btn = ttk.Button(recent_frame, text=name,
                                 bootstyle="secondary-link",
                                 command=lambda path=p: self._load_recent(path))
                btn.pack(side="left", padx=3)

        # Status bar
        self.status_bar = ttk.Frame(self, height=28)
        self.status_bar.pack(fill="x", side="bottom")
        self.status_bar.pack_propagate(False)

        self.status = ttk.Label(self.status_bar,
                                 text=f"{APP_NAME} v{VERSION} — Next-gen video codec",
                                 font=("Segoe UI", 9),
                                 bootstyle="inverse-secondary")
        self.status.pack(fill="both", expand=True, padx=10)

    def _load_recent(self, path):
        if os.path.exists(path):
            self.notebook.select(0)
            self.encode_tab._load_file(path)

    def _setup_bindings(self):
        self.bind("<Control-o>", lambda e: self.notebook.select(0) or
                   self.encode_tab._browse())
        self.bind("<Control-e>", lambda e: self.encode_tab._encode())
        self.bind("<Escape>", lambda e: self.encode_tab._cancel())
        self.bind("<Control-q>", lambda e: self.destroy())


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
