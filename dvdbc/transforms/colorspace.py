import numpy as np

def rgb_to_yuv(rgb: np.ndarray) -> np.ndarray:
    """RGB → YUV 4:4:4 (ITU-R BT.601)"""
    m = np.array([
        [ 0.299,  0.587,  0.114],
        [-0.147, -0.289,  0.436],
        [ 0.615, -0.515, -0.100],
    ], dtype=np.float32)
    yuv = rgb @ m.T
    yuv[..., 1:] += 0.5
    return yuv.astype(np.float32)

def yuv_to_rgb(yuv: np.ndarray) -> np.ndarray:
    """YUV 4:4:4 → RGB"""
    yuv = yuv.astype(np.float32)
    yuv[..., 1:] -= 0.5
    m = np.array([
        [1.0,  0.0,      1.140],
        [1.0, -0.394, -0.581],
        [1.0,  2.032,    0.0],
    ], dtype=np.float32)
    rgb = yuv @ m.T
    return np.clip(rgb, 0, 255).astype(np.uint8)

def yuv444_to_420(yuv: np.ndarray) -> np.ndarray:
    """Chroma subsampling 4:4:4 → 4:2:0"""
    h, w, _ = yuv.shape
    out = yuv.copy()
    for c in (1, 2):
        ch = yuv[..., c]
        ch_small = (ch[0::2, 0::2] + ch[0::2, 1::2] +
                    ch[1::2, 0::2] + ch[1::2, 1::2]) / 4.0
        out[..., c] = np.repeat(np.repeat(ch_small, 2, axis=0), 2, axis=1)
    return out

def yuv420_to_444(yuv: np.ndarray) -> np.ndarray:
    """Chroma upsampling 4:2:0 → 4:4:4 (reconstruct from quarter-res chroma)"""
    h, w, _ = yuv.shape
    out = yuv.copy()
    for c in (1, 2):
        ch = yuv[::2, ::2, c]
        out[..., c] = np.repeat(np.repeat(ch, 2, axis=0), 2, axis=1)
    return out
