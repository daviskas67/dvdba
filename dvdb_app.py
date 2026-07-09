#!/usr/bin/env python3
"""
DVDBA Desktop — красивый cross-platform GUI для DVDBC кодека.
"""

import os, sys, time, threading, json, struct
from pathlib import Path
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from ttkbootstrap.dialogs import Messagebox
from PIL import Image, ImageTk, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dvdbc.codec import encode_frame, decode_frame
from dvdbc.container import muxer
from dvdbc.quality import psnr, ssim
from dvdbc.cli import rgb_to_yuv_from_rgb

APP_NAME = "DVDBA Codec"
VERSION = "1.0.0"
CONFIG_FILE = Path.home() / ".dvdbarc"


class Settings:
    def __init__(self):
        self.load()

    def load(self):
        defaults = dict(theme="darkly", quality=50, keyframe=30, outdir=str(Path.home() / "Videos"))
        if CONFIG_FILE.exists():
            try:
                self.__dict__.update(json.loads(CONFIG_FILE.read_text()))
            except:
                self.__dict__.update(defaults)
        else:
            self.__dict__.update(defaults)
        for k, v in defaults.items():
            self.__dict__.setdefault(k, v)

    def save(self):
        CONFIG_FILE.write_text(json.dumps(self.__dict__, indent=2))


settings = Settings()


def format_size(b):
    for unit in ('B','KB','MB','GB'):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} TB"

def format_time(s):
    if s < 60:
        return f"{s:.1f}s"
    m, s = divmod(s, 60)
    return f"{int(m)}m {s:.0f}s"


class VideoCanvas(ttk.Frame):
    """Widget для отображения кадра видео."""

    def __init__(self, master, label="", **kw):
        super().__init__(master, **kw)
        self.label_text = label
        self._img = None
        self._photo = None
        self._size = (320, 240)

        self.label = ttk.Label(self, text=label, font=("Segoe UI", 10, "bold"))
        self.label.pack(pady=(0, 2))

        self.canvas = ttk.Canvas(self, width=320, height=240,
                                 highlightthickness=1,
                                 highlightbackground="#444")
        self.canvas.pack()

        self.info = ttk.Label(self, text="", font=("Segoe UI", 9))
        self.info.pack(pady=(2, 0))

        self._draw_placeholder()

    def _draw_placeholder(self, text=None):
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, 320, 240, fill="#1a1a2e", outline="")
        c.create_text(160, 115, text=text or f"<{self.label_text}>",
                      fill="#666", font=("Segoe UI", 14))

    def set_frame(self, rgb_array):
        h, w = rgb_array.shape[:2]
        # Scale to fit
        scale = min(320 / w, 240 / h)
        nw, nh = int(w * scale), int(h * scale)
        img = Image.fromarray(rgb_array).resize((nw, nh), Image.LANCZOS)
        # Center on canvas
        self._photo = ImageTk.PhotoImage(img)
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, 320, 240, fill="#1a1a2e", outline="")
        c.create_image((320 - nw)//2, (240 - nh)//2, anchor="nw", image=self._photo)
        self._size = (w, h)

    def set_info(self, text):
        self.info.config(text=text)


class EncodeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.input_path = None
        self.running = False
        self._setup_ui()

    def _setup_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)

        # Left panel - controls
        left = ttk.LabelFrame(self, text="Settings")
        left.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        ttk.Label(left, text="Input Video:").pack(anchor="w", padx=10, pady=(10,0))
        self.inp_btn = ttk.Button(left, text="Browse...", command=self._browse_input)
        self.inp_btn.pack(fill="x", pady=(0, 10))
        self.inp_lbl = ttk.Label(left, text="No file selected", font=("Segoe UI", 9))
        self.inp_lbl.pack(anchor="w", pady=(0, 10))

        ttk.Label(left, text="Quality (1-100):", font=("Segoe UI", 10)).pack(anchor="w")
        self.quality_var = ttk.IntVar(value=settings.quality)
        self.quality_slider = ttk.Scale(left, from_=1, to=100,
                                         variable=self.quality_var,
                                         command=self._on_quality)
        self.quality_slider.pack(fill="x", pady=2)
        self.quality_lbl = ttk.Label(left, text=f"Quality: {settings.quality}")
        self.quality_lbl.pack(anchor="w", pady=(0, 10))

        ttk.Label(left, text="Keyframe Interval:").pack(anchor="w")
        self.kf_var = ttk.IntVar(value=settings.keyframe)
        self.kf_spin = ttk.Spinbox(left, from_=1, to=300,
                                    textvariable=self.kf_var, width=8)
        self.kf_spin.pack(anchor="w", pady=(0, 10))

        self.encode_btn = ttk.Button(left, text="Encode", bootstyle="success",
                                      command=self._encode)
        self.encode_btn.pack(fill="x", pady=(10, 5))

        self.cancel_btn = ttk.Button(left, text="Cancel", bootstyle="secondary",
                                      state="disabled", command=self._cancel)
        self.cancel_btn.pack(fill="x")

        # Right panel - preview + progress
        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.preview = VideoCanvas(right, label="Preview")
        self.preview.pack(pady=5)

        self.progress = ttk.Progressbar(right, mode="determinate", value=0)
        self.progress.pack(fill="x", pady=5)

        self.status = ttk.Label(right, text="Ready", font=("Segoe UI", 9))
        self.status.pack(anchor="w")

        self.stats_text = ttk.Label(right, text="", font=("Segoe UI", 9),
                                     foreground="#aaa")
        self.stats_text.pack(anchor="w")

    def _on_quality(self, *a):
        v = self.quality_var.get()
        self.quality_lbl.config(text=f"Quality: {v}")

    def _browse_input(self):
        path = ttk.filedialog.askopenfilename(
            title="Select Video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.webm"),
                       ("All files", "*.*")]
        )
        if path:
            self.input_path = path
            self.inp_lbl.config(text=os.path.basename(path))
            self._show_preview(path)

    def _show_preview(self, path):
        if cv2 is None:
            return
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            self.preview.set_frame(rgb)
            h, w = frame.shape[:2]
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            size = os.path.getsize(path)
            self.preview.set_info(f"{w}x{h} | {fps:.0f} fps | {frames} frames | {format_size(size)}")

    def _encode(self):
        if not self.input_path:
            Messagebox.show_error("Select an input video first.", "Error")
            return
        if self.running:
            return

        out_path = ttk.filedialog.asksaveasfilename(
            defaultextension=".dvdbc",
            filetypes=[("DVDBC Video", "*.dvdbc"), ("All files", "*.*")]
        )
        if not out_path:
            return

        self.running = True
        self.encode_btn.config(state="disabled", text="Encoding...")
        self.cancel_btn.config(state="normal")

        quality = self.quality_var.get()
        keyframe = self.kf_var.get()
        settings.quality = quality
        settings.keyframe = keyframe
        settings.save()

        t = threading.Thread(target=self._encode_thread,
                             args=(self.input_path, out_path, quality, keyframe),
                             daemon=True)
        t.start()

    def _cancel(self):
        self.running = False
        self.encode_btn.config(state="normal", text="Encode")
        self.cancel_btn.config(state="disabled")
        self.status.config(text="Cancelled")
        self.progress["value"] = 0

    def _encode_thread(self, in_path, out_path, quality, keyframe):
        try:
            cap = cv2.VideoCapture(in_path)
            w = int(cap.get(3))
            h = int(cap.get(4))
            fps = cap.get(5)
            total = int(cap.get(7))
            if total <= 0:
                total = 100

            header = muxer.mux_header(w, h, fps, total, quality, keyframe)
            frames_data = []
            ref_y = None
            start = time.time()

            for i in range(total):
                if not self.running:
                    break
                ret, frame = cap.read()
                if not ret:
                    break
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                is_key = i % keyframe == 0
                fd, recon_y, _ = encode_frame(rgb, quality, None if is_key else ref_y)
                ref_y = recon_y
                frames_data.append(fd)

                # Update UI from main thread
                elapsed = time.time() - start
                pct = int((i + 1) / total * 100)
                fps_proc = (i + 1) / elapsed if elapsed > 0 else 0
                self.after(0, self._update_progress, pct,
                           f"Frame {i+1}/{total} ({fps_proc:.1f} fps)")

            cap.release()

            if self.running:
                with open(out_path, "wb") as f:
                    f.write(header)
                    for fd in frames_data:
                        f.write(fd)
                elapsed = time.time() - start
                sz = os.path.getsize(out_path)
                self.after(0, self._encode_done, len(frames_data), elapsed, sz)
            else:
                self.after(0, self._cancel)
        except Exception as e:
            self.after(0, self._encode_error, str(e))

    def _update_progress(self, pct, status):
        self.progress["value"] = pct
        self.status.config(text=status)

    def _encode_done(self, nframes, elapsed, size):
        self.running = False
        self.encode_btn.config(state="normal", text="Encode")
        self.cancel_btn.config(state="disabled")
        self.progress["value"] = 100
        self.status.config(text="Done!")
        self.stats_text.config(
            text=f"{nframes} frames encoded in {format_time(elapsed)} | {format_size(size)} | {nframes/elapsed:.1f} fps"
        )
        Messagebox.show_info(
            f"Encoded {nframes} frames in {format_time(elapsed)}\n"
            f"Output: {format_size(size)}\n"
            f"Speed: {nframes/elapsed:.1f} fps",
            "Encoding Complete"
        )

    def _encode_error(self, msg):
        self.running = False
        self.encode_btn.config(state="normal", text="Encode")
        self.cancel_btn.config(state="disabled")
        self.status.config(text="Error")
        Messagebox.show_error(msg, "Encoding Error")


class DecodeTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.running = False
        self._setup_ui()

    def _setup_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=2)

        left = ttk.LabelFrame(self, text="Settings")
        left.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        ttk.Label(left, text="DVDBC File:").pack(anchor="w", padx=10, pady=(10,0))
        self.inp_btn = ttk.Button(left, text="Browse...", command=self._browse)
        self.inp_btn.pack(fill="x", padx=10, pady=(0, 10))
        self.inp_lbl = ttk.Label(left, text="No file selected", font=("Segoe UI", 9))
        self.inp_lbl.pack(anchor="w", padx=10, pady=(0, 10))

        self.info_lbl = ttk.Label(left, text="", font=("Segoe UI", 9))
        self.info_lbl.pack(anchor="w", padx=10, pady=(0, 10))

        self.decode_btn = ttk.Button(left, text="Decode", bootstyle="success",
                                       command=self._decode)
        self.decode_btn.pack(fill="x", padx=10, pady=5)

        right = ttk.Frame(self)
        right.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)

        self.preview = VideoCanvas(right, label="Decoded")
        self.preview.pack(pady=5)

        self.progress = ttk.Progressbar(right, mode="determinate", value=0)
        self.progress.pack(fill="x", pady=5)

        self.status = ttk.Label(right, text="Ready", font=("Segoe UI", 9))
        self.status.pack(anchor="w")

    def _browse(self):
        path = ttk.filedialog.askopenfilename(
            title="Select DVDBC File",
            filetypes=[("DVDBC Video", "*.dvdbc"), ("All files", "*.*")]
        )
        if path:
            self.input_path = path
            self.inp_lbl.config(text=os.path.basename(path))
            with open(path, "rb") as f:
                data = f.read(muxer.HEADER_SIZE)
            info = muxer.parse_header(data)
            self.info_lbl.config(
                text=f"{info['width']}x{info['height']} | "
                     f"{info['fps']:.0f} fps | {info['frame_count']} frames | "
                     f"Quality: {info['quality']}"
            )

    def _decode(self):
        if not hasattr(self, 'input_path') or not self.input_path:
            Messagebox.show_error("Select a DVDBC file first.", "Error")
            return

        out_path = ttk.filedialog.asksaveasfilename(
            defaultextension=".mp4",
            filetypes=[("MP4 Video", "*.mp4"), ("All files", "*.*")]
        )
        if not out_path:
            return

        self.running = True
        self.decode_btn.config(state="disabled", text="Decoding...")

        t = threading.Thread(target=self._decode_thread,
                             args=(self.input_path, out_path), daemon=True)
        t.start()

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
            idx = 0
            total = info['frame_count']
            start = time.time()

            while offset < len(data) and self.running:
                rem = data[offset:]
                fsize = int.from_bytes(rem[1:5], 'big')
                rgb = decode_frame(rem[:5+fsize], info['width'], info['height'],
                                   info['quality'], ref_y)
                yuv = rgb_to_yuv_from_rgb(rgb)
                ref_y = yuv[..., 0].astype(np.uint8)
                out.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                offset += 5 + fsize
                idx += 1

                pct = int(idx / total * 100)
                self.after(0, self._update_progress, pct, f"Frame {idx}/{total}")

            out.release()
            elapsed = time.time() - start
            self.after(0, self._decode_done, idx, elapsed)
        except Exception as e:
            self.after(0, self._decode_error, str(e))

    def _update_progress(self, pct, status):
        self.progress["value"] = pct
        self.status.config(text=status)

    def _decode_done(self, nframes, elapsed):
        self.running = False
        self.decode_btn.config(state="normal", text="Decode")
        self.progress["value"] = 100
        self.status.config(text=f"Done! {nframes} frames in {format_time(elapsed)}")
        Messagebox.show_info(f"Decoded {nframes} frames in {format_time(elapsed)}",
                             "Decoding Complete")

    def _decode_error(self, msg):
        self.running = False
        self.decode_btn.config(state="normal", text="Decode")
        self.status.config(text="Error")
        Messagebox.show_error(msg, "Decoding Error")


class CompareTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self._setup_ui()

    def _setup_ui(self):
        self.columnconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        self.orig_canvas = VideoCanvas(self, label="Original")
        self.orig_canvas.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")

        self.dec_canvas = VideoCanvas(self, label="DVDBC Decoded")
        self.dec_canvas.grid(row=0, column=1, padx=5, pady=5, sticky="nsew")

        controls = ttk.Frame(self)
        controls.grid(row=1, column=0, columnspan=2, pady=10)

        ttk.Label(controls, text="Original:").pack(side="left", padx=5)
        self.orig_btn = ttk.Button(controls, text="Browse",
                                    command=self._browse_orig)
        self.orig_btn.pack(side="left", padx=5)
        self.orig_lbl = ttk.Label(controls, text="None", font=("Segoe UI", 9))
        self.orig_lbl.pack(side="left", padx=5)

        ttk.Label(controls, text="DVDBC:").pack(side="left", padx=5)
        self.comp_btn = ttk.Button(controls, text="Browse",
                                    command=self._browse_comp)
        self.comp_btn.pack(side="left", padx=5)
        self.comp_lbl = ttk.Label(controls, text="None", font=("Segoe UI", 9))
        self.comp_lbl.pack(side="left", padx=5)

        self.compare_btn = ttk.Button(controls, text="Compare", bootstyle="primary",
                                       command=self._compare)
        self.compare_btn.pack(side="left", padx=10)

        self.result_lbl = ttk.Label(self, text="", font=("Segoe UI", 11, "bold"))
        self.result_lbl.grid(row=2, column=0, columnspan=2, pady=5)

    def _browse_orig(self):
        p = ttk.filedialog.askopenfilename(title="Original Video",
                                            filetypes=[("Video", "*.mp4 *.avi *.mov"), ("*", "*.*")])
        if p:
            self.orig_path = p
            self.orig_lbl.config(text=os.path.basename(p))
            self._show_frame(p, self.orig_canvas)

    def _browse_comp(self):
        p = ttk.filedialog.askopenfilename(title="DVDBC File",
                                            filetypes=[("DVDBC", "*.dvdbc"), ("*", "*.*")])
        if p:
            self.comp_path = p
            self.comp_lbl.config(text=os.path.basename(p))

    def _show_frame(self, path, canvas):
        if cv2 is None:
            return
        cap = cv2.VideoCapture(path)
        ret, frame = cap.read()
        cap.release()
        if ret:
            canvas.set_frame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def _compare(self):
        if not hasattr(self, 'orig_path') or not hasattr(self, 'comp_path'):
            Messagebox.show_error("Select both files.", "Error")
            return

        self.compare_btn.config(state="disabled", text="Comparing...")
        self.result_lbl.config(text="")

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
                if not ret:
                    break
                orig_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rem = comp[offset:]
                fsize = int.from_bytes(rem[1:5], 'big')
                dec_rgb = decode_frame(rem[:5+fsize], info['width'],
                                       info['height'], info['quality'], ref_y)
                yuv = rgb_to_yuv_from_rgb(dec_rgb)
                ref_y = yuv[..., 0].astype(np.uint8)

                psnr_vals.append(psnr(orig_rgb, dec_rgb))
                ssim_vals.append(ssim(orig_rgb, dec_rgb))
                offset += 5 + fsize
                idx += 1

                if idx == 1:
                    self.after(0, self.orig_canvas.set_frame, orig_rgb)
                    self.after(0, self.dec_canvas.set_frame, dec_rgb)

            cap.release()

            if psnr_vals:
                avg_psnr = np.mean(psnr_vals)
                avg_ssim = np.mean(ssim_vals)
                orig_sz = os.path.getsize(self.orig_path)
                comp_sz = os.path.getsize(self.comp_path)

                self.after(0, self._show_results, idx, avg_psnr, avg_ssim,
                          orig_sz, comp_sz)
            else:
                self.after(0, self._compare_error, "No frames compared.")
        except Exception as e:
            self.after(0, self._compare_error, str(e))

    def _show_results(self, n, psnr_avg, ssim_avg, orig_sz, comp_sz):
        self.compare_btn.config(state="normal", text="Compare")
        self.orig_canvas.set_info(f"{format_size(orig_sz)}")
        self.dec_canvas.set_info(f"{format_size(comp_sz)} (ratio: {orig_sz/comp_sz:.2f}x)")
        self.result_lbl.config(
            text=f"PSNR: {psnr_avg:.2f} dB | SSIM: {ssim_avg:.4f} | "
                 f"Size: {format_size(orig_sz)} -> {format_size(comp_sz)} | "
                 f"Ratio: {orig_sz/comp_sz:.2f}x",
            foreground="#0f0" if psnr_avg > 35 else "#ff0"
        )

    def _compare_error(self, msg):
        self.compare_btn.config(state="normal", text="Compare")
        self.result_lbl.config(text=f"Error: {msg}", foreground="red")


class App(ttk.Window):
    def __init__(self):
        super().__init__(title=f"{APP_NAME} v{VERSION}",
                         themename=settings.theme,
                         size=(960, 680),
                         minsize=(800, 600))
        self.set_icon()
        self._setup_menu()
        self._setup_ui()

    def set_icon(self):
        try:
            icon = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
            draw = ImageDraw.Draw(icon)
            draw.ellipse([4, 4, 28, 28], fill="#00d4ff")
            draw.text((8, 8), "D", fill="#000")
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            icon.save(tmp.name)
            self.iconphoto(True, ImageTk.PhotoImage(file=tmp.name))
        except:
            pass

    def _setup_menu(self):
        mb = ttk.Menu(self)
        file_m = ttk.Menu(mb, tearoff=False)
        file_m.add_command(label="Open for Encode...", command=lambda: self._switch_tab(0))
        file_m.add_command(label="Open for Decode...", command=lambda: self._switch_tab(1))
        file_m.add_separator()
        file_m.add_command(label="Exit", command=self.destroy)
        mb.add_cascade(label="File", menu=file_m)

        theme_m = ttk.Menu(mb, tearoff=False)
        for t in ["darkly", "superhero", "cyborg", "vapor", "solar", "flatly", "litera"]:
            theme_m.add_command(label=t.capitalize(),
                                command=lambda tn=t: self._set_theme(tn))
        mb.add_cascade(label="Theme", menu=theme_m)

        help_m = ttk.Menu(mb, tearoff=False)
        help_m.add_command(label="About DVDBA", command=self._show_about)
        mb.add_cascade(label="Help", menu=help_m)

        self.config(menu=mb)

    def _set_theme(self, name):
        settings.theme = name
        settings.save()
        self.style.theme_use(name)

    def _switch_tab(self, idx):
        self.notebook.select(idx)

    def _setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=5, pady=5)

        self.encode_tab = EncodeTab(self.notebook, self)
        self.decode_tab = DecodeTab(self.notebook, self)
        self.compare_tab = CompareTab(self.notebook, self)

        self.notebook.add(self.encode_tab, text=" Encode ")
        self.notebook.add(self.decode_tab, text=" Decode ")
        self.notebook.add(self.compare_tab, text=" Compare ")

        # Status bar
        self.statusbar = ttk.Label(self, text=f"{APP_NAME} v{VERSION} | Ready",
                                    bootstyle="inverse-secondary")
        self.statusbar.pack(fill="x", side="bottom")

    def _show_about(self):
        Messagebox.show_info(
            f"{APP_NAME} v{VERSION}\n\n"
            f"A next-gen video codec that outperforms MP4\n"
            f"in quality while maintaining competitive sizes.\n\n"
            f"Technologies:\n"
            f"  - DCT + Adaptive Quantization\n"
            f"  - Motion Estimation / Compensation\n"
            f"  - Chroma Subsampling 4:2:0\n"
            f"  - Entropy Coding (RLE + Huffman)\n"
            f"  - Custom DVDBC Container\n\n"
            f"Built with Python, NumPy, OpenCV, ttkbootstrap",
            f"About {APP_NAME}"
        )


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
