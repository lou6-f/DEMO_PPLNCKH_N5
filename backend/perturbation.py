"""
perturbation.py
===============
JPEG-aware Protective Perturbation via PGD with Face Embedding surrogate loss.

Baseline  : Anti-DreamBooth (Van Le et al., ICCV 2023)
            delta* = argmax L_protect(x + delta; theta)
            
Improvement: JPEG-aware PGD (nhom NCKH)
            delta* = argmax L_protect(J~_Q(x + delta); theta),  Q in {50, 70, 90}

Surrogate model: Face Embedding (InceptionResnetV1 / FaceNet)
  — replaces the heavy Diffusion U-Net with a lightweight (~95 MB) face
    recognition encoder, enabling fast inference on CPU / consumer GPU.
"""

import math
import random
import time
import traceback
from io import BytesIO
from typing import Callable, Dict, Any, Optional, List

import numpy as np
import torch
import torch.nn.functional as F
import torchvision.transforms as T
from PIL import Image
from skimage.metrics import structural_similarity as ssim_fn

from diff_jpeg import DifferentiableJPEG


# ── Constants ────────────────────────────────────────────────────────────────

MAX_PROC_DIM = 512      # Long edge is capped here for performance


# ── Face surrogate model ─────────────────────────────────────────────────────

class FaceSurrogate:
    """
    Lightweight face embedding surrogate.

    Uses InceptionResnetV1 (FaceNet) pretrained on VGGFace2.
    Falls back to a torchvision feature extractor when facenet-pytorch
    is not installed.
    """

    FACE_IN = 160   # InceptionResnetV1 input resolution

    def __init__(self, device: str = 'cpu'):
        self.device = device
        self._face_box: Optional[List[int]] = None
        self._load()

    def _load(self):
        try:
            from facenet_pytorch import InceptionResnetV1, MTCNN
            self.mtcnn  = MTCNN(keep_all=False, device=self.device,
                                 post_process=False, select_largest=True,
                                 min_face_size=40)
            self.resnet = InceptionResnetV1(pretrained='vggface2').eval().to(self.device)
            self._backend = 'facenet'
            print('[Surrogate] Loaded: FaceNet InceptionResnetV1 (VGGFace2)')
        except Exception as e:
            print(f'[Surrogate] facenet-pytorch not available ({e}), using VGG fallback')
            import torchvision.models as M
            vgg = M.vgg16(weights=M.VGG16_Weights.IMAGENET1K_V1)
            self.feature_net = torch.nn.Sequential(
                *list(vgg.features.children())
            ).eval().to(self.device)
            self._backend = 'vgg'

    def detect_face(self, pil_img: Image.Image) -> Optional[List[int]]:
        """
        Returns [x1, y1, x2, y2] face bounding box or None.
        Coordinates are in the coordinate system of pil_img.
        """
        if self._backend != 'facenet':
            return None
        try:
            boxes, probs = self.mtcnn.detect(pil_img)
            if boxes is None or len(boxes) == 0:
                return None
            best = int(probs.argmax())
            box  = boxes[best]
            return [int(v) for v in box]   # [x1, y1, x2, y2]
        except Exception:
            return None

    def embed(self, x: torch.Tensor, box: Optional[List[int]] = None) -> torch.Tensor:
        """
        Compute L2-normalized embedding. Differentiable w.r.t. x.

        Args:
            x:   [B, 3, H, W] float tensor in [0, 1]  (on self.device)
            box: [x1, y1, x2, y2] face crop (optional)
        Returns:
            [B, D] normalized embedding
        """
        H, W = x.shape[2], x.shape[3]

        if self._backend == 'facenet':
            if box is not None:
                x1, y1, x2, y2 = box
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(W, x2), min(H, y2)
                if x2 > x1 + 8 and y2 > y1 + 8:
                    region = x[:, :, y1:y2, x1:x2]
                else:
                    region = x
            else:
                region = x

            face = F.interpolate(region, size=(self.FACE_IN, self.FACE_IN),
                                 mode='bilinear', align_corners=False)
            face = face * 2.0 - 1.0   # [0,1] -> [-1, 1]
            emb  = self.resnet(face)   # [B, 512]
        else:
            inp  = F.interpolate(x, size=(224, 224), mode='bilinear', align_corners=False)
            emb  = self.feature_net(inp).flatten(1)

        return F.normalize(emb, p=2, dim=1)   # [B, D]


# Global cached singleton so model is not reloaded on every call
_SURROGATE_CACHE: Optional[FaceSurrogate] = None

def get_surrogate(device: str = 'cpu') -> FaceSurrogate:
    global _SURROGATE_CACHE
    if _SURROGATE_CACHE is None or _SURROGATE_CACHE.device != device:
        _SURROGATE_CACHE = FaceSurrogate(device)
    return _SURROGATE_CACHE


# ── Metrics ──────────────────────────────────────────────────────────────────

def psnr(x: torch.Tensor, y: torch.Tensor) -> float:
    """PSNR (dB) between two [0,1] tensors."""
    mse = F.mse_loss(x, y).item()
    return 100.0 if mse < 1e-12 else 20.0 * math.log10(1.0 / math.sqrt(mse))


def estimate_dreambooth_metrics(epsilon: int) -> dict:
    """
    Interpolate expected Anti-DreamBooth metrics based on Table 3 in
    Anti-DreamBooth paper (ICCV 2023, VinAI Research) on VGGFace2 / CelebA-HQ.
    """
    eta = epsilon / 255.0
    if eta <= 0.01:
        t = eta / 0.01
        fdfr = 7.0 + t * (8.0 - 7.0)
        ism = 0.63 - t * (0.63 - 0.58)
        brisque = 15.61 + t * (33.03 - 15.61)
    elif eta <= 0.03:
        t = (eta - 0.01) / 0.02
        fdfr = 8.0 + t * (44.0 - 8.0)
        ism = 0.58 - t * (0.58 - 0.38)
        brisque = 33.03 + t * (36.45 - 33.03)
    elif eta <= 0.05:
        t = (eta - 0.03) / 0.02
        fdfr = 44.0 + t * (63.0 - 44.0)
        ism = 0.38 - t * (0.38 - 0.33)
        brisque = 36.45 + t * (36.42 - 36.45)
    elif eta <= 0.10:
        t = (eta - 0.05) / 0.05
        fdfr = 63.0 + t * (76.0 - 63.0)
        ism = 0.33 - t * (0.33 - 0.21)
        brisque = 36.42 + t * (37.33 - 36.42)
    else:
        t = min(1.0, (eta - 0.10) / 0.05)
        fdfr = 76.0 + t * (80.0 - 76.0)
        ism = 0.21 - t * (0.21 - 0.15)
        brisque = 37.33 + t * (37.07 - 37.33)

    return {
        'fdfr': round(fdfr, 1),
        'ism': round(ism, 2),
        'brisque': round(brisque, 1)
    }


# ── Core algorithm ────────────────────────────────────────────────────────────

def protect_image(
    image_pil:      Image.Image,
    epsilon:        int   = 8,
    iterations:     int   = 100,
    jpeg_qualities: list  = [50, 70, 90],
    mode:           str   = 'jpeg_aware',   # 'baseline' | 'jpeg_aware'
    device:         str   = 'cpu',
    progress_cb: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> tuple:
    """
    Generate JPEG-aware Protective Perturbation.

    Args:
        image_pil      : Input PIL image (RGB)
        epsilon        : L_inf budget in pixel units [0–255]
        iterations     : PGD iteration count
        jpeg_qualities : JPEG quality levels to randomly sample (mode='jpeg_aware')
        mode           : 'baseline' — no JPEG in loop (Anti-DreamBooth style)
                         'jpeg_aware' — differentiable JPEG inside loop (improvement)
        device         : torch device string
        progress_cb    : Optional callback(dict) for real-time UI progress

    Returns:
        (protected_pil: PIL.Image, residual_pil: PIL.Image, stats: dict)
    """

    def report(stage: str, pct: float, detail: str = ''):
        if progress_cb:
            progress_cb({'stage': stage, 'pct': round(pct, 1), 'detail': detail})

    t_start = time.time()

    # ── 1. Resize image for processing ────────────────────────────────────
    report('init', 2, 'Tiền xử lý và căn chỉnh ảnh...')

    W0, H0 = image_pil.size
    scale   = min(MAX_PROC_DIM / max(W0, H0), 1.0)
    proc_w  = max(8, int(W0 * scale) - int(W0 * scale) % 8)
    proc_h  = max(8, int(H0 * scale) - int(H0 * scale) % 8)

    proc_pil = image_pil.resize((proc_w, proc_h), Image.LANCZOS)

    to_t = T.ToTensor()
    to_p = T.ToPILImage()

    x_proc = to_t(proc_pil).unsqueeze(0).to(device)    # [1, 3, ph, pw]
    x_full = to_t(image_pil).unsqueeze(0).to(device)   # [1, 3, H0, W0]

    report('init', 5, f'Kích thước tối ưu: {W0}x{H0} -> {proc_w}x{proc_h}')

    # ── 2. Face detection via cached surrogate ─────────────────────────────
    report('init', 8, 'Phát hiện khuôn mặt chủ thể...')

    surrogate = get_surrogate(device)
    box_full  = surrogate.detect_face(image_pil)

    box_proc = None
    if box_full is not None:
        sx, sy = proc_w / W0, proc_h / H0
        x1, y1, x2, y2 = box_full
        box_proc = [int(x1*sx), int(y1*sy), int(x2*sx), int(y2*sy)]

    fd = box_proc is not None
    report('init', 10, f'Khuôn mặt: {"Đã định vị ✓" if fd else "Không tìm thấy rõ — bảo vệ toàn ảnh"}')

    # Pre-compute reference embedding (clean image target)
    with torch.no_grad():
        emb_ref = surrogate.embed(x_proc, box_proc)   # [1, D]

    # ── 3. Setup PGD ───────────────────────────────────────────────────────
    diff_jpeg = DifferentiableJPEG().to(device) if mode == 'jpeg_aware' else None
    eps       = epsilon / 255.0
    alpha     = eps * 2.5 / iterations

    delta     = torch.zeros_like(x_proc)  # [1, 3, ph, pw]

    report('pgd', 12, f'Bắt đầu PGD ({mode}) — ε={epsilon}/255, T={iterations}')

    # ── 4. PGD loop ───────────────────────────────────────────────────────
    log_every = max(1, iterations // 25)

    for t in range(iterations):
        d = delta.detach().requires_grad_(True)
        x_adv = x_proc + d   # [1, 3, ph, pw]

        # JPEG-aware mode: simulate differentiable JPEG inside loop
        if mode == 'jpeg_aware' and diff_jpeg is not None:
            Q     = random.choice(jpeg_qualities)
            x_in  = diff_jpeg(x_adv, Q)
        else:
            Q    = None
            x_in = x_adv

        # Surrogate loss: minimize cosine similarity -> maximize identity distance
        emb_pert = surrogate.embed(x_in, box_proc)
        loss = F.cosine_similarity(emb_ref.detach(), emb_pert, dim=1).mean()

        loss.backward()

        with torch.no_grad():
            # Gradient descent on similarity (making embeddings diverge)
            delta = delta - alpha * d.grad.sign()
            delta = delta.clamp(-eps, eps)

        if (t + 1) % log_every == 0:
            pct    = 12 + (t + 1) / iterations * 68
            detail = f'Vòng {t+1}/{iterations} | Độ tương đồng={loss.item():.4f}'
            if Q:
                detail += f' | Nén JPEG Q={Q}'
            report('pgd', pct, detail)

    # ── 5. Apply to full-resolution image ─────────────────────────────────
    report('apply', 82, 'Ghép lớp nhiễu đối kháng vào ảnh gốc...')

    with torch.no_grad():
        if proc_w != W0 or proc_h != H0:
            delta_up = F.interpolate(delta, size=(H0, W0),
                                     mode='bilinear', align_corners=False)
            delta_up = delta_up.clamp(-eps, eps)
        else:
            delta_up = delta

        x_prot = (x_full + delta_up).clamp(0.0, 1.0)

    # ── 6. Compute Residual / Heatmap ─────────────────────────────────────
    report('apply', 88, 'Tạo bản đồ nhiễu (Residual Map)...')
    with torch.no_grad():
        # Magnified absolute difference (15x) for intuitive human inspection
        diff_abs = (x_prot - x_full).abs()
        diff_amp = (diff_abs * 15.0).clamp(0.0, 1.0)
        res_pil = to_p(diff_amp.squeeze(0).cpu())

    prot_pil = to_p(x_prot.squeeze(0).cpu())

    # ── 7. Calculate Quantitative Metrics (PSNR, SSIM, Distance) ─────────
    report('stats', 92, 'Đo lường chỉ số khoa học (PSNR, SSIM, L_inf)...')

    with torch.no_grad():
        p = psnr(x_full, x_prot)
        max_d = float(delta_up.abs().max().item() * 255.0)
        l2_norm = float(torch.norm(delta_up).item())

        # Face distance on final protected image
        x_prot_proc = F.interpolate(x_prot, size=(proc_h, proc_w),
                                     mode='bilinear', align_corners=False)
        emb_prot = surrogate.embed(x_prot_proc, box_proc)
        sim_after = float(F.cosine_similarity(emb_ref, emb_prot, dim=1).mean().item())
        face_dist_pct = round((1.0 - sim_after) * 100, 1)

    # SSIM using skimage
    orig_np = np.array(image_pil)
    prot_np = np.array(prot_pil)
    val_ssim = round(float(ssim_fn(orig_np, prot_np, channel_axis=2)), 4)

    # ── 8. JPEG Robustness Evaluation (Q=90, Q=70, Q=50) ──────────────────
    report('stats', 96, 'Kiểm thử độ bền trước nén JPEG thực tế (Q=90, 70, 50)...')
    jpeg_eval = {}
    orig_noise_mean = float(np.mean(np.abs(prot_np.astype(float) - orig_np.astype(float)))) + 1e-6

    for q in [90, 70, 50]:
        buf = BytesIO()
        prot_pil.save(buf, 'JPEG', quality=q)
        buf.seek(0)
        q_img = Image.open(buf).convert('RGB')
        q_t = to_t(q_img).unsqueeze(0).to(device)

        # Measure face similarity after real JPEG
        q_proc = F.interpolate(q_t, size=(proc_h, proc_w), mode='bilinear', align_corners=False)
        with torch.no_grad():
            emb_q = surrogate.embed(q_proc, box_proc)
            sim_q = float(F.cosine_similarity(emb_ref, emb_q, dim=1).mean().item())

        # Measure noise retention
        q_np = np.array(q_img)
        diff_q = float(np.mean(np.abs(q_np.astype(float) - orig_np.astype(float))))
        retained_pct = round(min(100.0, (diff_q / orig_noise_mean) * 100.0), 1)

        psnr_q = round(psnr(x_full, q_t), 2)
        jpeg_eval[f'q{q}'] = {
            'quality': q,
            'face_dist_pct': round((1.0 - sim_q) * 100, 1),
            'noise_retention_pct': retained_pct,
            'psnr': psnr_q
        }

    # Anti-DreamBooth disruption regression estimates
    db_metrics = estimate_dreambooth_metrics(epsilon)

    elapsed = round(time.time() - t_start, 1)

    stats = {
        'psnr':                 round(p, 2),
        'ssim':                 val_ssim,
        'max_delta':            round(max_d, 2),
        'l2_norm':              round(l2_norm, 2),
        'epsilon':              epsilon,
        'iterations':           iterations,
        'mode':                 mode,
        'time_s':               elapsed,
        'face_detected':        fd,
        'face_dist_pct':        face_dist_pct,      # Face feature divergence
        'proc_size':            f'{proc_w}x{proc_h}',
        'orig_size':            f'{W0}x{H0}',
        'device':               device,
        'surrogate':            surrogate._backend,
        'jpeg_eval':            jpeg_eval,          # Survival at Q=90, 70, 50
        'dreambooth_est':       db_metrics,         # FDFR, ISM, BRISQUE
    }

    report('done', 100, f'Hoàn thành bảo vệ! PSNR={p:.1f} dB | SSIM={val_ssim} | Face Dist={face_dist_pct}%')

    return prot_pil, res_pil, stats
