"""
diff_jpeg.py
============
Differentiable JPEG approximation for use in adversarial optimization.

Implements JPEG compression with Straight-Through Estimator (STE) for
the quantization step, allowing gradient to flow through the pipeline.

Pipeline:
  RGB → YCbCr → level-shift → block-DCT → quantize(STE) → dequant
       → block-IDCT → level-restore → YCbCr → RGB

Reference:
  "Towards Evaluating the Robustness of Neural Networks", Carlini & Wagner 2017
  "Differentiable JPEG: The Devil is in the Details", Guo et al. 2023
"""

import math
import torch
import torch.nn as nn
import torch.nn.functional as F

# ── Standard JPEG quantization tables (MPEG-1 Annex K) ──────────────────────

_LUMA_Q = torch.tensor([
    [16, 11, 10, 16, 24,  40,  51,  61],
    [12, 12, 14, 19, 26,  58,  60,  55],
    [14, 13, 16, 24, 40,  57,  69,  56],
    [14, 17, 22, 29, 51,  87,  80,  62],
    [18, 22, 37, 56, 68,  109, 103, 77],
    [24, 35, 55, 64, 81,  104, 113, 92],
    [49, 64, 78, 87, 103, 121, 120, 101],
    [72, 92, 95, 98, 112, 100, 103, 99],
], dtype=torch.float32)

_CHROMA_Q = torch.tensor([
    [17, 18, 24, 47, 99, 99, 99, 99],
    [18, 21, 26, 66, 99, 99, 99, 99],
    [24, 26, 56, 99, 99, 99, 99, 99],
    [47, 66, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
    [99, 99, 99, 99, 99, 99, 99, 99],
], dtype=torch.float32)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _build_dct_matrix() -> torch.Tensor:
    """Orthonormal 8×8 DCT-II basis matrix."""
    N = 8
    D = torch.zeros(N, N)
    for k in range(N):
        for n in range(N):
            if k == 0:
                D[k, n] = 1.0 / math.sqrt(N)
            else:
                D[k, n] = math.sqrt(2.0 / N) * math.cos(math.pi * k * (2*n + 1) / (2.0 * N))
    return D


def _scale_qtable(base: torch.Tensor, quality: int) -> torch.Tensor:
    """Scale a standard quantization table by JPEG quality (1-100)."""
    quality = max(1, min(100, quality))
    if quality < 50:
        scale = 5000.0 / quality
    else:
        scale = 200.0 - 2.0 * quality
    return (base * scale / 100.0).clamp(1.0, 255.0).round()


def _ste_round(x: torch.Tensor) -> torch.Tensor:
    """
    Straight-Through Estimator rounding.
    Forward : x.round()
    Backward: gradient as if identity (passes straight through)
    """
    return x + (x.round() - x).detach()


# ── Main module ───────────────────────────────────────────────────────────────

class DifferentiableJPEG(nn.Module):
    """
    Differentiable JPEG compression module.

    Enables gradient flow through the JPEG pipeline during adversarial
    optimization by replacing the non-differentiable rounding in the
    quantization step with a Straight-Through Estimator.

    Usage::

        diff_jpeg = DifferentiableJPEG()
        x_jpeg = diff_jpeg(x, quality=75)   # x: [B, 3, H, W] in [0,1]
    """

    def __init__(self):
        super().__init__()
        D = _build_dct_matrix()                     # [8, 8]
        self.register_buffer('D',        D)
        self.register_buffer('luma_q',   _LUMA_Q)
        self.register_buffer('chroma_q', _CHROMA_Q)

    # ── Color space ──────────────────────────────────────────────────────

    @staticmethod
    def _rgb_to_ycbcr(x: torch.Tensor) -> torch.Tensor:
        """[B,3,H,W] ∈[0,1] → [B,3,H,W] ∈[0,1]  (Y, Cb, Cr)"""
        r, g, b = x[:, 0:1], x[:, 1:2], x[:, 2:3]
        y  =  0.299000*r + 0.587000*g + 0.114000*b
        cb = -0.168736*r - 0.331264*g + 0.500000*b + 0.5
        cr =  0.500000*r - 0.418688*g - 0.081312*b + 0.5
        return torch.cat([y, cb, cr], dim=1)

    @staticmethod
    def _ycbcr_to_rgb(x: torch.Tensor) -> torch.Tensor:
        """[B,3,H,W] ∈[0,1] → [B,3,H,W] ∈[0,1]"""
        y  = x[:, 0:1]
        cb = x[:, 1:2] - 0.5
        cr = x[:, 2:3] - 0.5
        r  = y + 1.402000*cr
        g  = y - 0.344136*cb - 0.714136*cr
        b  = y + 1.772000*cb
        return torch.cat([r, g, b], dim=1).clamp(0.0, 1.0)

    # ── Block DCT / IDCT ────────────────────────────────────────────────

    def _block_dct(self, x: torch.Tensor) -> torch.Tensor:
        """
        2-D block DCT on non-overlapping 8×8 tiles.
        x:      [B, C, H, W]  — H, W must be multiples of 8
        return: [B, C, H//8, W//8, 8, 8]
        """
        B, C, H, W = x.shape
        nh, nw = H // 8, W // 8
        D = self.D   # [8, 8]

        # [B*C, H, W] → unfold → [B*C, nh, nw, 8, 8]
        x2 = x.reshape(B * C, H, W)
        blocks = x2.unfold(1, 8, 8).unfold(2, 8, 8)  # [B*C, nh, nw, 8, 8]

        # 2-D DCT: D @ block @ Dᵀ
        dct = torch.matmul(D, blocks)   # [B*C, nh, nw, 8, 8]
        dct = torch.matmul(dct, D.t())  # [B*C, nh, nw, 8, 8]

        return dct.reshape(B, C, nh, nw, 8, 8)

    def _block_idct(self, dct: torch.Tensor) -> torch.Tensor:
        """
        2-D block IDCT — inverse of _block_dct.
        dct:    [B, C, nh, nw, 8, 8]
        return: [B, C, nh*8, nw*8]
        """
        B, C, nh, nw, _, _ = dct.shape
        H, W = nh * 8, nw * 8
        BC   = B * C
        D    = self.D   # [8, 8]

        flat = dct.reshape(BC, nh, nw, 8, 8)

        # 2-D IDCT: Dᵀ @ dct_block @ D
        rec = torch.matmul(D.t(), flat)  # [BC, nh, nw, 8, 8]
        rec = torch.matmul(rec, D)       # [BC, nh, nw, 8, 8]

        # Fold blocks back → [BC, 1, H, W]
        # F.fold input format: [BC, kernel_size_flat, L]
        rec = rec.reshape(BC, nh * nw, 64).permute(0, 2, 1)   # [BC, 64, nh*nw]
        x_rec = F.fold(rec, output_size=(H, W), kernel_size=(8, 8), stride=8)
        # x_rec: [BC, 1, H, W]

        return x_rec.squeeze(1).reshape(B, C, H, W)

    # ── Forward ─────────────────────────────────────────────────────────

    def forward(self, x: torch.Tensor, quality: int) -> torch.Tensor:
        """
        Args:
            x:       Float tensor [B, 3, H, W] in [0, 1]
            quality: JPEG quality factor (1–100)
        Returns:
            Float tensor [B, 3, H, W] in [0, 1]
        """
        B, C, H, W = x.shape
        dev = x.device

        # Pad H and W to multiples of 8
        ph = (8 - H % 8) % 8
        pw = (8 - W % 8) % 8
        if ph or pw:
            x = F.pad(x, (0, pw, 0, ph), mode='reflect')
        Hp, Wp = x.shape[2], x.shape[3]

        # RGB [0,1] → YCbCr [0,1] → [0,255] → level-shift → [-128, 127]
        ycbcr = self._rgb_to_ycbcr(x) * 255.0 - 128.0   # [B, 3, Hp, Wp]

        # Build quality-adjusted quantization tables
        lq = _scale_qtable(self.luma_q,   quality).to(dev)   # [8, 8]
        cq = _scale_qtable(self.chroma_q, quality).to(dev)   # [8, 8]
        qtabs = [lq, cq, cq]   # Y → luma; Cb, Cr → chroma

        rec_channels = []
        for c in range(3):
            ch  = ycbcr[:, c:c+1]           # [B, 1, Hp, Wp]
            q   = qtabs[c]                   # [8, 8]

            # Forward DCT  [B, 1, Hp//8, Wp//8, 8, 8]
            dct = self._block_dct(ch)

            # Quantize with STE, then dequantize
            q_exp  = q.view(1, 1, 1, 1, 8, 8)
            dct_q  = _ste_round(dct / q_exp) * q_exp

            # Inverse DCT  [B, 1, Hp, Wp]
            rec = self._block_idct(dct_q)
            rec_channels.append(rec)

        ycbcr_rec = torch.cat(rec_channels, dim=1)   # [B, 3, Hp, Wp]

        # Level-restore → [0,1] → YCbCr → RGB
        rgb = self._ycbcr_to_rgb((ycbcr_rec + 128.0) / 255.0)

        return rgb[:, :, :H, :W]   # remove padding
