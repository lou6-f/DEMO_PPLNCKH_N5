# HƯỚNG DẪN DEPLOY WEB APP CHO NHIỀU NGƯỜI DÙNG
### Đề tài: Xây dựng phương pháp bảo vệ ảnh nhằm hạn chế bị thu thập và sử dụng trái phép để huấn luyện mô hình AI (Anti-DreamBooth & JPEG-aware)

---

Hệ thống đã được tối ưu hóa sẵn sàng cho việc phục vụ **nhiều người dùng đồng thời (Multi-user concurrency)** với:
- **Server WSGI Production (Waitress / Gunicorn)**: Xử lý nhiều luồng HTTP request cùng lúc, không bị treo trang khi có nhiều người truy cập.
- **Hàng đợi thông minh (Concurrency Queue / Semaphore)**: Giới hạn số lượng tác vụ PGD PyTorch nặng chạy cùng lúc để không làm quá tải CPU/RAM, tự động xếp hàng và thông báo trạng thái tiến trình cho từng người dùng.
- **Tương thích đa nền tảng**: Đã có sẵn `Dockerfile`, `docker-compose.yml`, và script chia sẻ online tức thì.

Dưới đây là **4 phương án triển khai** tùy theo nhu cầu và tài nguyên của nhóm:

---

## 🚀 PHƯƠNG ÁN 1: Chia sẻ trực tiếp từ máy tính (Nhanh nhất - 1 Phút)
> **Phù hợp nhất:** Khi cần demo ngay cho Thầy Cô, Bạn bè hoặc Hội đồng chấm điểm truy cập thử từ điện thoại / laptop khác qua Internet mà không cần thuê server hay cấu hình phức tạp.

1. Đảm bảo máy tính của bạn đã bật server bằng cách chạy file `run.bat`.
2. Nhấn đúp chuột vào file **`share_online.bat`** trong thư mục dự án.
3. Script sẽ tự động kết nối qua **Cloudflare Tunnel** (bảo mật, miễn phí 100%, không cần đăng ký tài khoản).
4. Bạn sẽ thấy một đường link dạng:
   ```text
   https://random-subdomain.trycloudflare.com
   ```
5. **Gửi link này cho bất kỳ ai:** Họ có thể mở trên điện thoại (4G/Wifi) hoặc máy tính khác để tải ảnh lên và trải nghiệm đầy đủ tính năng!

---

## 🌐 PHƯƠNG ÁN 2: Deploy lên Hugging Face Spaces (Miễn phí 24/7 - Uy tín cho NCKH)
> **Phù hợp nhất cho đề tài Nghiên cứu Khoa học:** Hugging Face là nền tảng hàng đầu thế giới về AI. Tạo Space tại đây giúp nhóm có một đường link cố định (ví dụ: `https://huggingface.co/spaces/nhom5/PrivacyShield`) để chèn trực tiếp vào Báo cáo NCKH và Slide thuyết trình.

### Tài nguyên miễn phí:
- **16 GB RAM**, **2 vCPU** (mạnh mẽ hơn đa số laptop thông thường).
- Chạy liên tục 24/7, có chứng chỉ SSL/HTTPS tự động.

### Các bước thực hiện:
1. Đăng ký tài khoản tại [huggingface.co](https://huggingface.co) (nếu chưa có).
2. Nhấn **New Space** (hoặc truy cập `https://huggingface.co/new-space`).
3. Điền thông tin:
   - **Space name**: `privacyshield-antidreambooth`
   - **License**: `mit` hoặc `apache-2.0`
   - **Space SDK**: Chọn **Docker** -> **Blank**.
   - **Space hardware**: Chọn **CPU Basic (Free - 2 vCPU, 16GB RAM)**.
4. Clone repo của Space về máy tính hoặc upload toàn bộ thư mục dự án lên repo của Space (qua Git hoặc kéo thả trực tiếp trên giao diện web của Hugging Face):
   ```bash
   git remote add hf https://huggingface.co/spaces/<username>/privacyshield-antidreambooth
   git push hf main
   ```
5. Hugging Face sẽ tự động đọc file `Dockerfile` đã chuẩn bị sẵn, build container và kích hoạt trang web sau khoảng 2–3 phút!

---

## ☁️ PHƯƠNG ÁN 3: Deploy lên Cloud PaaS (Render / Railway / Koyeb)
> **Phù hợp:** Muốn tự động cập nhật web mỗi khi push code lên GitHub.

### Deploy trên Render.com:
1. Đưa mã nguồn lên một GitHub repository.
2. Đăng ký tài khoản tại [render.com](https://render.com).
3. Nhấn **New +** -> **Web Service**.
4. Kết nối tới repo GitHub của nhóm.
5. Ở phần **Environment**, Render sẽ tự nhận diện **Docker** (dựa trên `Dockerfile`).
6. Chọn gói **Free** (0.5 CPU, 512MB RAM) hoặc **Starter** và nhấn **Create Web Service**.
7. Render sẽ cấp một đường link cố định dạng `https://privacyshield.onrender.com`.

---

## 🖥️ PHƯƠNG ÁN 4: Deploy lên VPS riêng (Ubuntu / Debian Server)
> **Phù hợp:** Nhóm có sẵn VPS riêng (Vietnix, BKNS, DigitalOcean, Vultr, AWS EC2...).

1. Cài đặt Docker và Docker Compose trên VPS:
   ```bash
   sudo apt update && sudo apt install -y docker.io docker-compose
   ```
2. Copy thư mục dự án `Demo_PPLNCKH` lên VPS (qua SCP, FileZilla hoặc `git clone`).
3. Truy cập thư mục dự án trên VPS:
   ```bash
   cd Demo_PPLNCKH
   ```
4. Khởi chạy ứng dụng chạy ngầm trong container:
   ```bash
   docker-compose up -d --build
   ```
5. Mở trình duyệt và truy cập: `http://<IP_VPS>:5000`.
6. *(Tùy chọn nâng cao)*: Cấu hình Nginx reverse proxy và trỏ tên miền kèm SSL Let's Encrypt (Certbot).

---

## 📊 Tóm tắt so sánh các phương án:

| Tiêu chí | P1: Cloudflare Tunnel | P2: Hugging Face Spaces | P3: Render / Railway | P4: VPS riêng |
| :--- | :--- | :--- | :--- | :--- |
| **Chi phí** | 100% Miễn phí | 100% Miễn phí | Miễn phí (bị giới hạn RAM) | Có phí thuê VPS |
| **Thời gian làm** | 1 phút | 5 phút | 5 phút | 15 phút |
| **Thời gian chạy** | Khi máy tính còn bật | 24/7 liên tục | 24/7 | 24/7 |
| **Cấu hình phần cứng** | Tận dụng CPU máy bạn | 2 vCPU, 16GB RAM | 0.5 CPU, 512MB RAM | Theo gói VPS |
| **Khuyên dùng cho** | **Demo gấp, báo cáo trực tiếp** | **Đính kèm bài báo NCKH** | Web phụ trợ | Dự án thương mại |
