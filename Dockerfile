# ==============================================================================
# Dockerfile cho PrivacyShield - Anti-DreamBooth & JPEG-aware Perturbation
# Ho tro deploy tren: Render, Hugging Face Spaces, Railway, Koyeb, VPS Docker
# ==============================================================================

FROM python:3.10-slim

# Ngăn Python tạo file .pyc, log tức thì, và tắt cảnh báo root của pip
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_ROOT_USER_ACTION=ignore
ENV PORT=10000

WORKDIR /app

# Cài đặt các thư viện hệ thống cần thiết cho OpenCV, Pillow và PyTorch
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt Python dependencies (sử dụng PyTorch CPU siêu nhẹ ~170MB giúp Render build cực nhanh)
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r /app/backend/requirements.txt

# Copy toàn bộ mã nguồn
COPY backend/ /app/backend/
COPY frontend/ /app/frontend/

# Thiết lập thư mục làm việc
WORKDIR /app/backend

# Mở các cổng thông dụng
EXPOSE 10000 7860 5000

# Khởi chạy server production Waitress
CMD ["python", "app.py"]
