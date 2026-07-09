import numpy as np
from scipy import fftpack

def dct_2d(block: np.ndarray) -> np.ndarray:
    """Forward DCT-II on 8x8 block"""
    return fftpack.dct(fftpack.dct(block, axis=0, norm='ortho'), axis=1, norm='ortho')

def idct_2d(block: np.ndarray) -> np.ndarray:
    """Inverse DCT on 8x8 block"""
    return fftpack.idct(fftpack.idct(block, axis=0, norm='ortho'), axis=1, norm='ortho')

QUANT_LUM = np.array([
    [16, 11, 10, 16, 24, 40, 51, 61],
    [12, 12, 14, 19, 26, 58, 60, 55],
    [14, 13, 16, 24, 40, 57, 69, 56],
    [14, 17, 22, 29, 51, 87, 80, 62],
    [18, 22, 37, 56, 68, 109, 103, 77],
    [24, 35, 55, 64, 81, 104, 113, 92],
    [49, 64, 78, 87, 103, 121, 120, 101],
    [72, 92, 95, 98, 112, 100, 103, 99],
], dtype=np.float32)

QUANT_CHROM = np.array([
    [17, 18, 24, 47, 99, 99, 99, 99],
    [18, 21, 26, 66, 99, 99, 99, 99],
    [24, 26, 56, 99, 99, 99, 99, 99],
    [47, 66, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
], dtype=np.float32)

def quantize(block: np.ndarray, qtable: np.ndarray, qscale: float = 1.0) -> np.ndarray:
    """Quantize DCT coefficients. qscale=1.0 = JPEG default, higher = finer."""
    q = qtable * (1.0 / max(qscale, 0.01))
    return np.round(block / q).astype(np.int32)

def dequantize(block: np.ndarray, qtable: np.ndarray, qscale: float = 1.0) -> np.ndarray:
    """Dequantize DCT coefficients."""
    q = qtable * (1.0 / max(qscale, 0.01))
    return (block * q).astype(np.float32)

def zigzag_indices() -> np.ndarray:
    """Zigzag scan order for 8x8 block"""
    idx = np.array([
        [ 0,  1,  5,  6, 14, 15, 27, 28],
        [ 2,  4,  7, 13, 16, 26, 29, 42],
        [ 3,  8, 12, 17, 25, 30, 41, 43],
        [ 9, 11, 18, 24, 31, 40, 44, 53],
        [10, 19, 23, 32, 39, 45, 52, 54],
        [20, 22, 33, 38, 46, 51, 55, 60],
        [21, 34, 37, 47, 50, 56, 59, 61],
        [35, 36, 48, 49, 57, 58, 62, 63],
    ])
    return idx

def zigzag_scan(block: np.ndarray) -> np.ndarray:
    """Flatten 8x8 to 64-elem in zigzag order"""
    zz = zigzag_indices()
    flat = np.zeros(64, dtype=block.dtype)
    flat[zz.ravel()] = block.ravel()
    return flat

def zigzag_unscan(flat: np.ndarray) -> np.ndarray:
    """Unflatten 64-elem zigzag to 8x8 (inverse of zigzag_scan)"""
    zz = zigzag_indices()
    return flat[zz.ravel()].reshape(8, 8)
