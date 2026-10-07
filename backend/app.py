"""
app.py
======
Flask backend for the JPEG-aware Protective Perturbation web demo.
Based on Anti-DreamBooth (ICCV 2023) and PTIT Methodology Research Report.

Endpoints:
  GET  /                          — serve frontend web app
  GET  /api/info                  — server info (device, status)
  GET  /api/samples               — list sample portrait images
  GET  /samples/<filename>        — serve sample image file
  POST /api/protect               — submit protection job
  GET  /api/progress/<job_id>     — SSE stream: real-time progress
  GET  /api/result/<job_id>       — final stats (when done)
  GET  /api/image/<job_id>/<type> — serve original / protected / residual image
  GET  /api/download/<job_id>     — download protected image
  GET  /api/jpeg_test/<job_id>    — serve JPEG-compressed version (robustness demo)
"""

import os
import sys

# Ensure UTF-8 output on Windows console
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

import json
import time
import uuid
import threading
import traceback
from io import BytesIO
from pathlib import Path

from flask import Flask, request, jsonify, Response, send_file, send_from_directory
from flask_cors import CORS
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from perturbation import protect_image
from simulation import generate_dreambooth_simulations

# ── App setup ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent / 'frontend'
SAMPLES_DIR = BASE_DIR / 'samples'
OUT_DIR = BASE_DIR / 'outputs'

OUT_DIR.mkdir(exist_ok=True)
SAMPLES_DIR.mkdir(exist_ok=True)

app = Flask(__name__, static_folder=str(FRONTEND_DIR), static_url_path='')
CORS(app, resources={r"/*": {"origins": "*"}})

# Job store: job_id -> dict
JOBS: dict = {}
_LOCK = threading.Lock()

# Auto-detect best device
def _device() -> str:
    try:
        import torch
        if torch.cuda.is_available():
            return 'cuda'
        try:
            if torch.backends.mps.is_available():
                return 'mps'
        except Exception:
            pass
    except Exception:
        pass
    return 'cpu'

DEVICE = _device()
print(f'[Backend] Running on device: {DEVICE}')

# Pre-warm FaceNet surrogate model in background at startup so first user has zero wait time
def _warmup_model():
    try:
        from perturbation import get_surrogate
        print('[Warmup] Preloading FaceNet surrogate weights into memory...')
        get_surrogate(DEVICE)
        print('[Warmup] FaceNet surrogate is cached and ready!')
    except Exception as e:
        print(f'[Warmup] Preload note: {e}')

threading.Thread(target=_warmup_model, daemon=True).start()


# ── Background worker ────────────────────────────────────────────────────────

def _run_job(job_id: str, img_bytes: bytes, params: dict):
    def cb(data: dict):
        with _LOCK:
            if job_id in JOBS:
                JOBS[job_id]['events'].append(data)

    try:
        # Immediately report 5% so progress bar starts moving instantly
        cb({'stage': 'init', 'pct': 5.0, 'detail': 'Khởi tạo ảnh và căn chỉnh khuôn mặt...'})

        pil = Image.open(BytesIO(img_bytes)).convert('RGB')

        # Save original
        orig_path = OUT_DIR / f'{job_id}_orig.png'
        pil.save(orig_path)
        with _LOCK:
            JOBS[job_id]['orig_path'] = str(orig_path)

        protected_pil, residual_pil, stats = protect_image(
            pil,
            epsilon        = params['epsilon'],
            iterations     = params['iterations'],
            jpeg_qualities = params['qualities'],
            mode           = params['mode'],
            device         = DEVICE,
            progress_cb    = cb,
        )

        out_path = OUT_DIR / f'{job_id}_protected.png'
        protected_pil.save(out_path)

        res_path = OUT_DIR / f'{job_id}_residual.png'
        residual_pil.save(res_path)

        # Generate DreamBooth disruption simulation examples
        try:
            sim_data = generate_dreambooth_simulations(str(orig_path), OUT_DIR, job_id)
            stats['simulation'] = sim_data
        except Exception as sim_err:
            print(f'[Job {job_id[:8]}] Sim error: {sim_err}')

        with _LOCK:
            JOBS[job_id].update(
                status='done',
                stats=stats,
                out_path=str(out_path),
                res_path=str(res_path)
            )

    except Exception as exc:
        err = traceback.format_exc()
        print(f'[Job {job_id[:8]}] ERROR: {exc}\n{err}')
        with _LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(status='error', error=str(exc))


# ── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
def serve_index():
    return send_from_directory(FRONTEND_DIR, 'index.html')


@app.route('/api/info')
def api_info():
    return jsonify({
        'device': DEVICE,
        'status': 'ready',
        'backend': 'PyTorch + FaceNet (VGGFace2) + DiffJPEG',
        'paper': 'Anti-DreamBooth (ICCV 2023)'
    })


@app.route('/api/samples')
def api_samples():
    sample_list = []
    if SAMPLES_DIR.exists():
        metadata = {
            'sample_female.jpg': {
                'name': 'Chân dung nữ (CelebA-HQ)',
                'desc': 'Góc nhìn chính diện, ánh sáng đều, độ phân giải cao'
            },
            'sample_male.jpg': {
                'name': 'Chân dung nam (VGGFace2)',
                'desc': 'Ánh sáng tự nhiên, góc chụp chuẩn đối kháng'
            },
            'sample_portrait.jpg': {
                'name': 'Chân dung ngoại cảnh',
                'desc': 'Bối cảnh ngoài trời, đặc trưng chi tiết phức tạp'
            }
        }
        for f in SAMPLES_DIR.glob('*.jpg'):
            meta = metadata.get(f.name, {'name': f.stem, 'desc': 'Ảnh chân dung thử nghiệm'})
            sample_list.append({
                'id': f.name,
                'name': meta['name'],
                'desc': meta['desc'],
                'url': f'/samples/{f.name}'
            })
    return jsonify({'samples': sample_list})


@app.route('/samples/<path:filename>')
def serve_sample(filename):
    return send_from_directory(SAMPLES_DIR, filename)


@app.route('/api/protect', methods=['POST'])
def api_protect():
    if 'image' not in request.files:
        return jsonify({'error': 'Vui lòng tải lên một tệp ảnh'}), 400

    try:
        img_bytes = request.files['image'].read()
        f = request.form
        iter_req = int(f.get('iterations', 20))
        # Cap iterations to 30 max on CPU to guarantee 10-15s execution time
        safe_iters = max(10, min(iter_req, 30))

        params = {
            'epsilon'   : int(f.get('epsilon', 8)),
            'iterations': safe_iters,
            'qualities' : json.loads(f.get('qualities', '[50,70,90]')),
            'mode'      : f.get('mode', 'jpeg_aware'),
        }
    except Exception as e:
        return jsonify({'error': f'Tham số không hợp lệ: {e}'}), 400

    job_id = str(uuid.uuid4())
    with _LOCK:
        JOBS[job_id] = {
            'status'   : 'running',
            'events'   : [],
            'stats'    : None,
            'out_path' : None,
            'res_path' : None,
            'orig_path': None,
            'error'    : None,
        }

    threading.Thread(target=_run_job, args=(job_id, img_bytes, params),
                     daemon=True).start()
    return jsonify({'job_id': job_id})


@app.route('/api/progress/<job_id>')
def api_progress(job_id):
    """Server-Sent Events stream for real-time progress updates."""
    def _gen_with_cursor():
        cursor = 0
        while True:
            with _LOCK:
                job = JOBS.get(job_id)
                if job is None:
                    yield f"data: {json.dumps({'type':'error','message':'Job không tồn tại'})}\n\n"
                    return
                new_ev = job['events'][cursor:]
                cursor += len(new_ev)
                status = job['status']
                stats  = job['stats']
                error  = job['error']

            for ev in new_ev:
                yield f"data: {json.dumps({'type':'progress', **ev})}\n\n"

            if status == 'done':
                yield f"data: {json.dumps({'type':'done','stats':stats})}\n\n"
                return
            if status == 'error':
                yield f"data: {json.dumps({'type':'error','message':error})}\n\n"
                return

            if not new_ev:
                yield ": keep-alive\n\n"

            time.sleep(0.3)

    return Response(_gen_with_cursor(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache, no-transform',
                             'X-Accel-Buffering': 'no',
                             'Connection': 'keep-alive'})


@app.route('/api/result/<job_id>')
def api_result(job_id):
    with _LOCK:
        job = JOBS.get(job_id, {})
    if not job:
        return jsonify({'error': 'Job không tồn tại'}), 404
    if job.get('status') == 'error':
        return jsonify({'status': 'error', 'error': job.get('error')}), 500
    if job.get('status') != 'done':
        last_ev = job.get('events', [])[-1] if job.get('events') else {}
        return jsonify({'status': 'running', 'progress': last_ev}), 202
    return jsonify({'status': 'done', 'stats': job.get('stats', {})})


@app.route('/api/image/<job_id>/<img_type>')
def api_image(job_id, img_type):
    """Serve original, protected, or residual image."""
    with _LOCK:
        job = JOBS.get(job_id, {})

    if img_type == 'original':
        key = 'orig_path'
    elif img_type == 'residual':
        key = 'res_path'
    else:
        key = 'out_path'

    path = job.get(key)
    if not path or not os.path.exists(path):
        return jsonify({'error': 'Ảnh không tìm thấy'}), 404

    fmt = request.args.get('fmt', 'png').lower()
    q   = int(request.args.get('quality', 92))

    img = Image.open(path).convert('RGB')
    buf = BytesIO()
    if fmt == 'jpeg':
        img.save(buf, 'JPEG', quality=q)
        mime = 'image/jpeg'
    elif fmt == 'webp':
        img.save(buf, 'WebP', quality=q)
        mime = 'image/webp'
    else:
        img.save(buf, 'PNG')
        mime = 'image/png'

    buf.seek(0)
    return send_file(buf, mimetype=mime)


@app.route('/api/download/<job_id>')
def api_download(job_id):
    with _LOCK:
        job = JOBS.get(job_id, {})
    path = job.get('out_path')
    if not path or not os.path.exists(path):
        return jsonify({'error': 'Không tìm thấy ảnh để tải'}), 404

    fmt = request.args.get('fmt', 'png').lower()
    q   = int(request.args.get('quality', 92))

    img = Image.open(path).convert('RGB')
    buf = BytesIO()
    if fmt == 'jpeg':
        img.save(buf, 'JPEG', quality=q)
        mime, ext = 'image/jpeg', 'jpg'
    elif fmt == 'webp':
        img.save(buf, 'WebP', quality=q)
        mime, ext = 'image/webp', 'webp'
    else:
        img.save(buf, 'PNG')
        mime, ext = 'image/png', 'png'

    buf.seek(0)
    return send_file(buf, mimetype=mime, as_attachment=True,
                     download_name=f'protected_antidreambooth_{job_id[:8]}.{ext}')


@app.route('/api/jpeg_test/<job_id>')
def api_jpeg_test(job_id):
    """
    Apply real (non-differentiable) JPEG compression and return result.
    Used by frontend to demo robustness at Q=50/70/90.
    """
    with _LOCK:
        job = JOBS.get(job_id, {})

    img_type = request.args.get('type', 'protected')
    quality  = int(request.args.get('quality', 70))

    if img_type == 'original':
        key = 'orig_path'
    elif img_type == 'residual':
        key = 'res_path'
    else:
        key = 'out_path'

    path = job.get(key)
    if not path or not os.path.exists(path):
        return jsonify({'error': 'Không tìm thấy tệp'}), 404

    img = Image.open(path).convert('RGB')
    buf = BytesIO()
    img.save(buf, 'JPEG', quality=quality)
    buf.seek(0)

    # Reload JPEG -> re-encode as PNG for lossless transmission to browser
    img_j = Image.open(buf)
    out = BytesIO()
    img_j.save(out, 'PNG')
    out.seek(0)

    return send_file(out, mimetype='image/png')


@app.route('/api/simulation_image/<job_id>/<sim_type>')
def api_sim_image(job_id, sim_type):
    """Serve simulated DreamBooth generation images."""
    valid_types = {
        'clean': f'{job_id}_sim_clean.png',
        'baseline': f'{job_id}_sim_baseline.png',
        'baseline_jpeg': f'{job_id}_sim_baseline_jpeg.png',
        'jpegaware_jpeg': f'{job_id}_sim_jpegaware_jpeg.png',
    }
    fname = valid_types.get(sim_type)
    if not fname:
        return jsonify({'error': 'Loại mô phỏng không hợp lệ'}), 400

    path = OUT_DIR / fname
    if not path.exists():
        return jsonify({'error': 'Ảnh mô phỏng chưa sẵn sàng'}), 404

    return send_file(path, mimetype='image/png')


PORT = int(os.environ.get('PORT', 5000))

if __name__ == '__main__':
    print('=' * 65)
    print('  PrivacyShield Backend - Anti-DreamBooth & JPEG-aware Perturbation')
    print(f'  Hardware Device: {DEVICE}')
    print(f'  Web App & API   : http://0.0.0.0:{PORT}')
    print('=' * 65)
    try:
        from waitress import serve
        print(f'  [Production WSGI] Serving with Waitress (threads=6) on port {PORT}...')
        serve(app, host='0.0.0.0', port=PORT, threads=6)
    except Exception as e:
        print(f'  [Fallback Flask] Running standard server: {e}')
        app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)
