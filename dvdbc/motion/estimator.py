import numpy as np

def sad(a: np.ndarray, b: np.ndarray) -> float:
    """Sum of Absolute Differences"""
    return float(np.sum(np.abs(a.astype(np.int32) - b.astype(np.int32))))

def motion_estimate(ref: np.ndarray, cur: np.ndarray,
                    block_size: int = 16, search_radius: int = 8) -> np.ndarray:
    """
    Motion estimation using exhaustive search.
    Returns motion vectors array of shape (H/bs, W/bs, 2).
    """
    h, w = cur.shape
    mv_rows = h // block_size
    mv_cols = w // block_size
    mv = np.zeros((mv_rows, mv_cols, 2), dtype=np.int32)
    pad = search_radius

    ref_pad = np.pad(ref, pad, mode='edge')

    for r in range(mv_rows):
        for c in range(mv_cols):
            y = r * block_size
            x = c * block_size
            best_sad = float('inf')
            best_dy, best_dx = 0, 0
            cb = cur[y:y+block_size, x:x+block_size]

            for dy in range(-search_radius, search_radius + 1):
                for dx in range(-search_radius, search_radius + 1):
                    ry = y + dy + pad
                    rx = x + dx + pad
                    rb = ref_pad[ry:ry+block_size, rx:rx+block_size]
                    if rb.shape != cb.shape:
                        continue
                    s = sad(cb, rb)
                    if s < best_sad:
                        best_sad = s
                        best_dy, best_dx = dy, dx

            mv[r, c] = [best_dy, best_dx]

    return mv

def motion_compensate(ref: np.ndarray, mv: np.ndarray,
                       block_size: int = 16) -> np.ndarray:
    """Apply motion vectors to reference frame to create prediction."""
    h, w = ref.shape
    pred = np.zeros_like(ref)
    mv_rows, mv_cols = mv.shape[:2]

    for r in range(mv_rows):
        for c in range(mv_cols):
            dy, dx = mv[r, c]
            y = r * block_size
            x = c * block_size
            sy = max(0, min(y + dy, h - block_size))
            sx = max(0, min(x + dx, w - block_size))
            pred[y:y+block_size, x:x+block_size] = ref[sy:sy+block_size, sx:sx+block_size]

    return pred
