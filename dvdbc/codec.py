"""
DVDBC Encoder / Decoder — the core compression engine.
Quality: 1-100 (higher = better, like JPEG). Default 50.
Chroma: 4:2:0 subsampling for ~50% chroma reduction.
"""

import struct
import numpy as np
from .transforms.colorspace import rgb_to_yuv, yuv_to_rgb
from .transforms.dct import (
    dct_2d, idct_2d, quantize, dequantize,
    QUANT_LUM, QUANT_CHROM, zigzag_scan, zigzag_unscan
)
from .entropy.huffman import RLEPlusHuffman
from .motion.estimator import motion_estimate, motion_compensate
from .container import muxer

BLOCK_SIZE = 8

def _to_qscale(quality: float) -> float:
    """Convert 1-100 quality to internal scale factor. Higher = less loss."""
    q = max(1.0, min(100.0, quality))
    return q / 50.0  # 50 = qtable * 1.0 (JPEG default)

def _pack(data: bytes) -> bytes:
    return struct.pack('!I', len(data)) + data

def _unpack(data: bytes, offset: int) -> tuple:
    length = struct.unpack_from('!I', data, offset)[0]
    offset += 4
    return data[offset:offset+length], offset + length

def encode_frame(rgb: np.ndarray, quality: float = 50.0,
                 ref_y: np.ndarray = None) -> tuple:
    yuv = rgb_to_yuv(rgb)
    h, w, _ = yuv.shape
    qs = _to_qscale(quality)
    is_key = ref_y is None

    if not is_key:
        mv = motion_estimate(ref_y, yuv[..., 0], 16, 8)
        pred_y = motion_compensate(ref_y, mv, 16)
        residual_y = yuv[..., 0] - pred_y
    else:
        mv = None
        residual_y = yuv[..., 0].copy()

    # Luma: full resolution
    y_comp = _compress_plane(residual_y if not is_key else yuv[..., 0], qs, QUANT_LUM)

    # Chroma: subsample 4:2:0 (half resolution)
    ch = (h + 1) // 2
    cw = (w + 1) // 2
    u_small = yuv[::2, ::2, 1] if h % 2 == 0 else yuv[:h-1:2, :w-1:2, 1]
    v_small = yuv[::2, ::2, 2] if h % 2 == 0 else yuv[:h-1:2, :w-1:2, 2]
    u_comp = _compress_plane(u_small[:ch, :cw], qs, QUANT_CHROM)
    v_comp = _compress_plane(v_small[:ch, :cw], qs, QUANT_CHROM)

    payload = _pack(y_comp) + _pack(u_comp) + _pack(v_comp)
    if mv is not None:
        payload += _pack(mv.tobytes())

    recon_y = _reconstruct_y(residual_y, pred_y if not is_key else None, qs)
    return muxer.mux_frame(0 if is_key else 1, payload), recon_y, mv


def _reconstruct_y(plane: np.ndarray, pred: np.ndarray or None, qs: float) -> np.ndarray:
    processed = _process_intra(plane, qs, QUANT_LUM)
    recon = (pred + processed) if pred is not None else processed
    return np.clip(recon, 0, 255).astype(np.uint8)


def _process_intra(plane: np.ndarray, qs: float, qtable: np.ndarray) -> np.ndarray:
    h, w = plane.shape
    out = np.zeros_like(plane, dtype=np.float32)
    for y in range(0, h, BLOCK_SIZE):
        for x in range(0, w, BLOCK_SIZE):
            block = plane[y:y+BLOCK_SIZE, x:x+BLOCK_SIZE].copy()
            if block.shape != (BLOCK_SIZE, BLOCK_SIZE):
                block = np.pad(block, ((0, BLOCK_SIZE-block.shape[0]),
                                       (0, BLOCK_SIZE-block.shape[1])), mode='edge')
            dct = dct_2d(block)
            q = quantize(dct, qtable, qs)
            dq = dequantize(q, qtable, qs)
            recon = idct_2d(dq)
            out[y:y+block.shape[0], x:x+block.shape[1]] = recon[:block.shape[0], :block.shape[1]]
    return out


def _compress_plane(plane: np.ndarray, qs: float, qtable: np.ndarray) -> bytes:
    h, w = plane.shape
    coeffs = []
    for y in range(0, h, BLOCK_SIZE):
        for x in range(0, w, BLOCK_SIZE):
            block = plane[y:y+BLOCK_SIZE, x:x+BLOCK_SIZE].copy()
            if block.shape != (BLOCK_SIZE, BLOCK_SIZE):
                block = np.pad(block, ((0, BLOCK_SIZE-block.shape[0]),
                                       (0, BLOCK_SIZE-block.shape[1])), mode='edge')
            dct = dct_2d(block)
            q = quantize(dct, qtable, qs)
            coeffs.extend(zigzag_scan(q).tolist())
    return RLEPlusHuffman.encode_coeffs(np.array(coeffs, dtype=np.int32))


def decode_frame(frame_data: bytes, width: int, height: int,
                 quality: float = 50.0, ref_y: np.ndarray = None) -> np.ndarray:
    ftype, fsize, off = muxer.parse_frame_header(frame_data, 0)
    payload = frame_data[off:off+fsize]
    qs = _to_qscale(quality)
    is_key = (ftype == 0)

    off = 0
    y_data, off = _unpack(payload, off)
    u_data, off = _unpack(payload, off)
    v_data, off = _unpack(payload, off)

    mv = None
    if off < len(payload):
        mv_raw, _ = _unpack(payload, off)
        mv = np.frombuffer(mv_raw, dtype=np.int32).reshape(height // 16, width // 16, 2)

    y_plane = _decompress_plane(y_data, height, width, qs, QUANT_LUM)
    ch = (height + 1) // 2
    cw = (width + 1) // 2
    u_small = _decompress_plane(u_data, ch, cw, qs, QUANT_CHROM)
    v_small = _decompress_plane(v_data, ch, cw, qs, QUANT_CHROM)

    # Upsample chroma to full resolution
    u_plane = np.repeat(np.repeat(u_small, 2, axis=0), 2, axis=1)[:height, :width]
    v_plane = np.repeat(np.repeat(v_small, 2, axis=0), 2, axis=1)[:height, :width]

    if not is_key and ref_y is not None and mv is not None:
        pred_y = motion_compensate(ref_y, mv, 16)
        y_plane = np.clip(pred_y + y_plane, 0, 255)

    yuv = np.stack([y_plane, u_plane, v_plane], axis=-1)
    return yuv_to_rgb(yuv)


def _decompress_plane(data: bytes, height: int, width: int,
                      qs: float, qtable: np.ndarray) -> np.ndarray:
    coeffs = RLEPlusHuffman.decode_coeffs(data)
    nblocks = ((height + BLOCK_SIZE - 1) // BLOCK_SIZE) * ((width + BLOCK_SIZE - 1) // BLOCK_SIZE)
    expected = nblocks * 64
    if len(coeffs) < expected:
        coeffs = np.pad(coeffs, (0, expected - len(coeffs)))
    coeffs = coeffs[:expected]

    plane = np.zeros((height, width), dtype=np.float32)
    idx = 0
    for y in range(0, height, BLOCK_SIZE):
        for x in range(0, width, BLOCK_SIZE):
            bh = min(BLOCK_SIZE, height - y)
            bw = min(BLOCK_SIZE, width - x)
            zz = coeffs[idx:idx+64]
            idx += 64
            dq = dequantize(zigzag_unscan(zz), qtable, qs)
            recon = idct_2d(dq)
            plane[y:y+bh, x:x+bw] = recon[:bh, :bw]
    return plane
