import numpy as np

def psnr(original: np.ndarray, compressed: np.ndarray) -> float:
    """Peak Signal-to-Noise Ratio in dB"""
    mse = np.mean((original.astype(np.float64) - compressed.astype(np.float64)) ** 2)
    if mse == 0:
        return float('inf')
    return 20 * np.log10(255.0 / np.sqrt(mse))

def ssim(original: np.ndarray, compressed: np.ndarray) -> float:
    """Structural Similarity Index (simplified, luminance only)"""
    if original.ndim == 3:
        # Convert to grayscale
        orig_gray = 0.299 * original[..., 0] + 0.587 * original[..., 1] + 0.114 * original[..., 2]
        comp_gray = 0.299 * compressed[..., 0] + 0.587 * compressed[..., 1] + 0.114 * compressed[..., 2]
    else:
        orig_gray = original.astype(np.float64)
        comp_gray = compressed.astype(np.float64)

    mu1 = np.mean(orig_gray)
    mu2 = np.mean(comp_gray)
    sigma1_sq = np.var(orig_gray)
    sigma2_sq = np.var(comp_gray)
    sigma12 = np.mean((orig_gray - mu1) * (comp_gray - mu2))

    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2

    ssim_val = ((2 * mu1 * mu2 + c1) * (2 * sigma12 + c2)) / \
               ((mu1 ** 2 + mu2 ** 2 + c1) * (sigma1_sq + sigma2_sq + c2))
    return float(ssim_val)

def compression_ratio(original_size: int, compressed_size: int) -> float:
    return original_size / compressed_size if compressed_size > 0 else 0.0
