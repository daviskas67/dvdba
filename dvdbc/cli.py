"""
DVDBC Command Line Interface

Usage:
  python -m dvdbc encode <input.mp4> <output.dvdbc> [--quality Q]
  python -m dvdbc decode <input.dvdbc> <output.mp4>
  python -m dvdbc compare <original.mp4> <compressed.dvdbc>
"""

import argparse
import os
import sys
import time
import numpy as np

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from .codec import encode_frame, decode_frame
from .container import muxer
from .quality import psnr, ssim, compression_ratio


def print_banner():
    print("=" * 60)
    print("  DVDBC — Davis's Digital Video Broadcast Codec v1.0")
    print("  «Дайте MP4 пососать»")
    print("=" * 60)


def cmd_encode(args):
    if not HAS_CV2:
        print("ERROR: OpenCV required for encoding. Install: pip install opencv-python")
        sys.exit(1)

    print_banner()
    print(f"\n[*] Encoding: {args.input} → {args.output}")
    print(f"[*] Quality: {args.quality}")

    cap = cv2.VideoCapture(args.input)
    if not cap.isOpened():
        print(f"ERROR: Cannot open {args.input}")
        sys.exit(1)

    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if total_frames <= 0:
        total_frames = 100  # estimate

    print(f"    Resolution: {width}x{height}, FPS: {fps:.2f}, Frames: {total_frames}")

    keyframe_interval = args.keyframe or 30
    quality = args.quality

    # Prepare output
    header = muxer.mux_header(width, height, fps, total_frames, quality, keyframe_interval)

    encoded_frames = []
    ref_y = None
    frame_idx = 0

    start_time = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        is_keyframe = (frame_idx % keyframe_interval == 0)

        frame_data, recon_y, mv = encode_frame(
            frame_rgb, quality,
            ref_y=None if is_keyframe else ref_y
        )

        if is_keyframe:
            ref_y = recon_y
        else:
            ref_y = recon_y

        encoded_frames.append(frame_data)

        if frame_idx % 10 == 0:
            elapsed = time.time() - start_time
            fps_proc = (frame_idx + 1) / elapsed if elapsed > 0 else 0
            print(f"\r    Frame {frame_idx + 1}/{total_frames} ({fps_proc:.1f} fps)", end='')

        frame_idx += 1
        if args.max_frames and frame_idx >= args.max_frames:
            break

    cap.release()

    print(f"\n[*] Encoding complete. Writing container...")

    with open(args.output, 'wb') as f:
        f.write(header)
        for fd in encoded_frames:
            f.write(fd)

    elapsed = time.time() - start_time
    file_size = os.path.getsize(args.output)

    print(f"\n[✓] Done! {frame_idx} frames encoded in {elapsed:.1f}s")
    print(f"    Output: {args.output} ({file_size / 1024:.1f} KB)")


def cmd_decode(args):
    if not HAS_CV2:
        print("ERROR: OpenCV required for decoding. Install: pip install opencv-python")
        sys.exit(1)

    print_banner()
    print(f"\n[*] Decoding: {args.input} → {args.output}")

    with open(args.input, 'rb') as f:
        data = f.read()

    info = muxer.parse_header(data)
    print(f"    Resolution: {info['width']}x{info['height']}")
    print(f"    Frames: {info['frame_count']}, Quality: {info['quality']}")

    width, height = info['width'], info['height']
    quality = info['quality']
    fps = info['fps']

    codec = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(args.output, codec, fps, (width, height))

    offset = muxer.HEADER_SIZE
    ref_y = None
    frame_idx = 0

    start_time = time.time()

    while offset < len(data):
        remaining = data[offset:]
        if len(remaining) < 5:
            break

        ftype = remaining[0]
        fsize = int.from_bytes(remaining[1:5], 'big')
        frame_payload = remaining[:5 + fsize]

        try:
            rgb = decode_frame(frame_payload, width, height, quality, ref_y)
        except Exception as e:
            print(f"\n[!] Error decoding frame {frame_idx}: {e}")
            break

        # Update ref_y
        yuv = rgb_to_yuv_from_rgb(rgb)
        ref_y = yuv[..., 0].astype(np.uint8)

        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        out.write(bgr)

        if frame_idx % 10 == 0:
            elapsed = time.time() - start_time
            fps_proc = (frame_idx + 1) / elapsed if elapsed > 0 else 0
            print(f"\r    Frame {frame_idx + 1}/{info['frame_count']} ({fps_proc:.1f} fps)", end='')

        offset += 5 + fsize
        frame_idx += 1

    out.release()
    elapsed = time.time() - start_time
    print(f"\n[✓] Decoded {frame_idx} frames in {elapsed:.1f}s → {args.output}")


def rgb_to_yuv_from_rgb(rgb: np.ndarray) -> np.ndarray:
    """Quick RGB→YUV for ref frame storage."""
    m = np.array([[0.299, 0.587, 0.114],
                  [-0.147, -0.289, 0.436],
                  [0.615, -0.515, -0.100]], dtype=np.float32)
    yuv = rgb.astype(np.float32) @ m.T
    yuv[..., 1:] += 0.5
    return yuv


def cmd_compare(args):
    if not HAS_CV2:
        print("ERROR: OpenCV required for comparison. Install: pip install opencv-python")
        sys.exit(1)

    print_banner()
    print(f"\n[*] Comparing: {args.original} vs {args.compressed}")

    # Open original
    cap_orig = cv2.VideoCapture(args.original)
    # Read compressed
    with open(args.compressed, 'rb') as f:
        comp_data = f.read()

    info = muxer.parse_header(comp_data)
    width, height = info['width'], info['height']
    quality = info['quality']

    offset = muxer.HEADER_SIZE
    ref_y = None
    frame_idx = 0

    psnr_vals = []
    ssim_vals = []

    while offset < len(comp_data):
        ret, frame_orig_bgr = cap_orig.read()
        if not ret:
            break

        frame_orig_rgb = cv2.cvtColor(frame_orig_bgr, cv2.COLOR_BGR2RGB)

        remaining = comp_data[offset:]
        ftype = remaining[0]
        fsize = int.from_bytes(remaining[1:5], 'big')
        frame_payload = remaining[:5 + fsize]

        try:
            frame_dec_rgb = decode_frame(frame_payload, width, height, quality, ref_y)
        except Exception as e:
            print(f"\n[!] Error at frame {frame_idx}: {e}")
            break

        yuv = rgb_to_yuv_from_rgb(frame_dec_rgb)
        ref_y = yuv[..., 0].astype(np.uint8)

        p = psnr(frame_orig_rgb, frame_dec_rgb)
        s = ssim(frame_orig_rgb, frame_dec_rgb)
        psnr_vals.append(p)
        ssim_vals.append(s)

        if frame_idx % 10 == 0:
            print(f"\r    Frame {frame_idx}: PSNR={p:.2f} dB, SSIM={s:.4f}", end='')

        offset += 5 + fsize
        frame_idx += 1

    cap_orig.release()

    if psnr_vals:
        orig_size = os.path.getsize(args.original)
        comp_size = os.path.getsize(args.compressed)
        cr = compression_ratio(orig_size, comp_size)

        print(f"\n\n[✓] Results ({frame_idx} frames):")
        print(f"    PSNR:  {np.mean(psnr_vals):.2f} dB (min: {np.min(psnr_vals):.2f}, max: {np.max(psnr_vals):.2f})")
        print(f"    SSIM:  {np.mean(ssim_vals):.4f}")
        print(f"    Size:  {orig_size / 1024:.1f} KB → {comp_size / 1024:.1f} KB")
        print(f"    Ratio: {cr:.2f}x")
        print(f"    Quality setting: {quality}")
    else:
        print("\n[!] No frames compared.")


def main():
    parser = argparse.ArgumentParser(
        description='DVDBC — Davis Digital Video Broadcast Codec',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m dvdbc encode input.mp4 output.dvdbc --quality 0.5
  python -m dvdbc decode output.dvdbc decoded.mp4
  python -m dvdbc compare input.mp4 output.dvdbc
        """
    )
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Encode
    p_enc = subparsers.add_parser('encode', help='Encode video to DVDBC format')
    p_enc.add_argument('input', help='Input video file')
    p_enc.add_argument('output', help='Output .dvdbc file')
    p_enc.add_argument('--quality', type=float, default=1.0,
                       help='Quality factor (lower = less loss, default: 1.0)')
    p_enc.add_argument('--keyframe', type=int, default=30,
                       help='Keyframe interval (default: 30)')
    p_enc.add_argument('--max-frames', type=int, default=None,
                       help='Max frames to encode')

    # Decode
    p_dec = subparsers.add_parser('decode', help='Decode DVDBC to video')
    p_dec.add_argument('input', help='Input .dvdbc file')
    p_dec.add_argument('output', help='Output video file')

    # Compare
    p_cmp = subparsers.add_parser('compare', help='Compare original with compressed')
    p_cmp.add_argument('original', help='Original video file')
    p_cmp.add_argument('compressed', help='Compressed .dvdbc file')

    args = parser.parse_args()

    if args.command == 'encode':
        cmd_encode(args)
    elif args.command == 'decode':
        cmd_decode(args)
    elif args.command == 'compare':
        cmd_compare(args)


if __name__ == '__main__':
    main()
