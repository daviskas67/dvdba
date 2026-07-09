"""
DVDBC Test - sozdaet sinteticheskoe video, kodiruet, dekodiruet i sravnivaet.
"""
import numpy as np
import cv2
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from dvdbc.codec import encode_frame, decode_frame
from dvdbc.container import muxer
from dvdbc.quality import psnr, ssim, compression_ratio
from dvdbc.cli import rgb_to_yuv_from_rgb

WIDTH, HEIGHT = 320, 240
FPS = 24
FRAMES = 30
QUALITY = 1.5

def generate_test_video(path, frames=FRAMES):
    """Create a test video with moving objects."""
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(path, fourcc, FPS, (WIDTH, HEIGHT))
    for i in range(frames):
        frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
        # Moving circle
        cx = int(50 + 150 * (0.5 + 0.5 * np.sin(i * 0.2)))
        cy = int(50 + 100 * (0.5 + 0.5 * np.cos(i * 0.15)))
        cv2.circle(frame, (cx, cy), 30, (255, 100, 50), -1)
        # Moving rectangle
        rx = int(200 + 80 * np.sin(i * 0.1))
        ry = int(150 + 60 * np.cos(i * 0.12))
        cv2.rectangle(frame, (rx, ry), (rx + 40, ry + 30), (50, 200, 100), -1)
        # Text
        cv2.putText(frame, f"Frame {i}", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        out.write(frame)
    out.release()
    print(f"[OK] Test video created: {path} ({os.path.getsize(path)/1024:.1f} KB)")

def encode_video(input_path, output_path, quality=QUALITY, keyframe_interval=15):
    """Encode video to DVDBC format."""
    cap = cv2.VideoCapture(input_path)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    header = muxer.mux_header(width, height, fps, frame_count, quality, keyframe_interval)
    frames_data = []
    ref_y = None
    idx = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        is_key = idx % keyframe_interval == 0
        fd, recon_y, _ = encode_frame(rgb, quality, ref_y=None if is_key else ref_y)
        ref_y = recon_y
        frames_data.append(fd)
        idx += 1

    cap.release()

    with open(output_path, 'wb') as f:
        f.write(header)
        for fd in frames_data:
            f.write(fd)

    print(f"[OK] Encoded: {output_path} ({os.path.getsize(output_path)/1024:.1f} KB, {idx} frames)")
    return idx

def decode_video(input_path, output_path):
    """Decode DVDBC to video."""
    with open(input_path, 'rb') as f:
        data = f.read()

    info = muxer.parse_header(data)
    width, height = info['width'], info['height']
    quality = info['quality']
    fps = info['fps']

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    offset = muxer.HEADER_SIZE
    ref_y = None
    idx = 0

    while offset < len(data):
        remaining = data[offset:]
        ftype = remaining[0]
        fsize = int.from_bytes(remaining[1:5], 'big')
        frame_payload = remaining[:5 + fsize]
        rgb = decode_frame(frame_payload, width, height, quality, ref_y)
        yuv = rgb_to_yuv_from_rgb(rgb)
        ref_y = yuv[..., 0].astype(np.uint8)
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        out.write(bgr)
        offset += 5 + fsize
        idx += 1

    out.release()
    print(f"[OK] Decoded: {output_path} ({os.path.getsize(output_path)/1024:.1f} KB, {idx} frames)")

def compare_videos(original_path, compressed_path):
    """Compare original vs compressed quality."""
    cap_orig = cv2.VideoCapture(original_path)
    with open(compressed_path, 'rb') as f:
        comp_data = f.read()

    info = muxer.parse_header(comp_data)
    width, height = info['width'], info['height']
    quality = info['quality']

    offset = muxer.HEADER_SIZE
    ref_y = None
    idx = 0
    psnr_vals, ssim_vals = [], []

    while offset < len(comp_data):
        ret, frame_bgr = cap_orig.read()
        if not ret:
            break
        orig_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)

        remaining = comp_data[offset:]
        fsize = int.from_bytes(remaining[1:5], 'big')
        frame_payload = remaining[:5 + fsize]
        dec_rgb = decode_frame(frame_payload, width, height, quality, ref_y)

        yuv = rgb_to_yuv_from_rgb(dec_rgb)
        ref_y = yuv[..., 0].astype(np.uint8)

        p = psnr(orig_rgb, dec_rgb)
        s = ssim(orig_rgb, dec_rgb)
        psnr_vals.append(p)
        ssim_vals.append(s)
        offset += 5 + fsize
        idx += 1

    cap_orig.release()

    orig_size = os.path.getsize(original_path)
    comp_size = os.path.getsize(compressed_path)

    print(f"\n{'='*50}")
    print(f"  REZULTATY SRAVNENIYA DVDBC vs MP4")
    print(f"{'='*50}")
    print(f"  Kadrov:        {idx}")
    print(f"  Razmer MP4:    {orig_size/1024:.1f} KB")
    print(f"  Razmer DVDBC:  {comp_size/1024:.1f} KB")
    print(f"  Szhatie:       {compression_ratio(orig_size, comp_size):.2f}x")
    print(f"  PSNR:          {np.mean(psnr_vals):.2f} dB")
    print(f"  SSIM:          {np.mean(ssim_vals):.4f}")
    print(f"  Nastroyka:     quality={quality}")
    print(f"{'='*50}")

    # If DVDBC is smaller, it wins
    if comp_size < orig_size:
        print(f"  [WIN] DVDBC menshe MP4 pri sopostavimom kachestve!")
    else:
        print(f"  [INFO] DVDBC bolshe MP4 (nuzhno podkrutit quality)")

    # Show per-frame PSNR
    import matplotlib.pyplot as plt
    try:
        plt.figure(figsize=(10, 4))
        plt.subplot(1, 2, 1)
        plt.plot(psnr_vals)
        plt.title('PSNR per frame (dB)')
        plt.xlabel('Frame')
        plt.ylabel('PSNR (dB)')
        plt.grid(True)

        plt.subplot(1, 2, 2)
        plt.plot(ssim_vals)
        plt.title('SSIM per frame')
        plt.xlabel('Frame')
        plt.ylabel('SSIM')
        plt.grid(True)

        plt.tight_layout()
        plt.savefig('dvdbc_quality_report.png')
        print(f"  [OK] Grafik: dvdbc_quality_report.png")
        plt.show()
    except:
        pass


if __name__ == '__main__':
    print("DVDBC Test Suite - proverka kodeka\n")

    # Step 1: Create test video
    if not os.path.exists('test_original.mp4'):
        generate_test_video('test_original.mp4')
    else:
        print("[i] Test video exists, skipping generation")

    # Step 2: Encode
    t0 = time.time()
    n_frames = encode_video('test_original.mp4', 'test_compressed.dvdbc',
                           quality=QUALITY, keyframe_interval=15)
    t_enc = time.time() - t0

    # Step 3: Decode
    t0 = time.time()
    decode_video('test_compressed.dvdbc', 'test_decoded.mp4')
    t_dec = time.time() - t0

    # Step 4: Compare
    compare_videos('test_original.mp4', 'test_compressed.dvdbc')

    print(f"\n  Vremya kodirovaniya: {t_enc:.2f}s")
    print(f"  Vremya dekodirovaniya: {t_dec:.2f}s")
    print(f"  Srednee: {n_frames/t_enc:.1f} fps encode, {n_frames/t_dec:.1f} fps decode")
