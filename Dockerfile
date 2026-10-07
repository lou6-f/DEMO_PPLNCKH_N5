# ==============================================================================
# Dockerfile cho PrivacyShield - Anti-DreamBooth & JPEG-aware Perturbation
# Ho tro deploy tren: Hugging Face Spaces, Render, Railway, Koyeb, va VPS Docker
# ==============================================================================

FROM python:3.10-slim

# Ngăn Python tạo file .pyc và hiển thị log ngay lập tức
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860

WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết cho OpenCV, Pillow và PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy toàn bộ mã nguồn
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Thiết lập quyền và thư mục làm việc
WORKDIR /app/backend

# Mở cổng (7860 cho Hugging Face Spaces, hoặc nhận từ $PORT trên Render/Railway)
EXPOSE 7860 5000

# Chạy ứng dụng bằng Waitress hoặc Gunicorn
CMD ["python", "app.py"]
