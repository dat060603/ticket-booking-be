# 🏟️ Hệ Thống Đặt Vé Sự Kiện Thể Thao (Sports Ticket Booking System) - Backend API

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![Django](https://img.shields.io/badge/Django-4.2-092E20.svg)
![Django REST Framework](https://img.shields.io/badge/DRF-API-red.svg)
![MySQL](https://img.shields.io/badge/MySQL-8.0-orange.svg)
![Redis](https://img.shields.io/badge/Redis-Cache%20%7C%20Locking-DC382D.svg)
![AI](https://img.shields.io/badge/AI-RAG%20%7C%20Machine%20Learning-8A2BE2.svg)

Đây là kho lưu trữ mã nguồn **Backend** (RESTful API) cho Đồ án tốt nghiệp: "Xây dựng website đặt vé xem sự kiện thể thao". Hệ thống được thiết kế theo kiến trúc Client-Server, tập trung giải quyết các bài toán về xử lý đồng thời (Concurrency), tính khả dụng của tài nguyên thời gian thực (Real-time) và tích hợp Trí tuệ nhân tạo (AI/ML) để tối ưu hóa quy trình kinh doanh.

🔗 **Frontend Repository:** (https://github.com/dat060603/ticket-booking-fe.git)

---

## 🚀 Điểm nhấn Kỹ thuật (Technical Highlights)

Dự án không chỉ là một hệ thống CRUD thông thường mà còn giải quyết các bài toán thực tế phức tạp:

* **Concurrency & Resource Locking:** Sử dụng **Redis TTL** để xây dựng cơ chế "Giữ ghế tạm thời" (Temporary Locking) trong 3 phút. Giải quyết triệt để bài toán Race Condition (xung đột dữ liệu) khi hàng ngàn người dùng cùng tranh mua vé tại một thời điểm (Overselling prevention).
* **Real-time Broadcasting:** Tích hợp **WebSocket (Django Channels)** đóng vai trò như một lớp phát tín hiệu (Signaling Layer). Ngay khi có ghế bị khóa hoặc thanh toán thành công, trạng thái ghế được đẩy (push) tức thì đến tất cả người dùng đang xem trận đấu đó mà không cần tải lại trang.
* **Asynchronous Processing:** Sử dụng **Celery + Redis** làm Message Broker để xử lý các tác vụ ngầm tốn thời gian như: Gửi Email tự động (khi đặt vé/hoàn vé thành công), xử lý logic hoàn tiền, và gọi API mô hình học máy mà không làm nghẽn luồng chính (Main thread).
* **AI - Smart Pricing (Machine Learning):** Ứng dụng thuật toán **Random Forest Regressor** (thay vì Linear Regression để xử lý dữ liệu phi tuyến tính) nhằm phân tích hành vi khách hàng, độ HOT của trận đấu. Từ đó gợi ý mức giá tối ưu (Sweet Spot) giúp Admin tối đa hóa doanh thu nhưng vẫn đảm bảo tỷ lệ lấp đầy sân.
* **AI - Customer Support Agent (Hybrid RAG):** Tích hợp Chatbot thông minh sử dụng kiến trúc **RAG (Retrieval-Augmented Generation)** kết hợp LLM (LLaMA 3 qua Groq API) và Vector Database (ChromaDB). AI có khả năng truy xuất lịch thi đấu, giá vé thời gian thực để tư vấn khách hàng chính xác tuyệt đối, loại bỏ hoàn toàn hiện tượng "ảo giác" (Hallucination).

---

## 🛠️ Công nghệ sử dụng (Tech Stack)

* **Core Framework:** Python, Django, Django REST Framework (DRF)
* **Database:** MySQL (Relational DB), Redis (In-memory DB / Message Broker)
* **Real-time:** Django Channels, WebSockets
* **Background Tasks:** Celery
* **Payment Gateway:** MoMo API (Sandbox Environment) tích hợp Webhook (IPN)
* **AI & Machine Learning:** Scikit-learn (Random Forest), LangChain, ChromaDB, HuggingFace Embeddings, Groq API (LLaMA 3.1)
* **Security:** JWT (JSON Web Tokens) Authentication, OTP Verification, AES Encryption.

---

## 📦 Chức năng Cốt lõi (Core Features)

### 🧑‍💼 Phân hệ Quản trị (Admin & Employee)
* **Quản lý Tài nguyên Thể thao:** CRUD toàn diện hệ thống Giải đấu, Đội bóng, Sân vận động, Sơ đồ khu vực (Sections) và Trận đấu.
* **Quản lý Vé & Kinh doanh:** Khởi tạo vé theo khu vực, cấu hình giá, quản lý các chiến dịch Khuyến mãi (Promotions).
* **Hệ thống AI Hỗ trợ ra quyết định (DSS):** * AI dự báo doanh thu và khuyến nghị giá vé (Price Optimization).
    * AI khuyến nghị mức giảm giá/khuyến mãi hợp lý.
* **Xử lý Giao dịch & Hoàn vé:** Theo dõi luồng đơn hàng, xử lý yêu cầu hoàn vé (Refund) tự động cộng lại ghế vào kho và dùng Celery gửi Email thông báo.
* **Quản trị Hệ thống:** Quản lý nhân viên, phân quyền truy cập, quản lý tệp khách hàng, hệ thống tích điểm (Loyalty Points) và Báo cáo/Thống kê Dashboard (Doanh thu, Tỷ lệ lấp đầy).

### 🙍‍♂️ Phân hệ Khách hàng (Customer)
* **Xác thực:** Đăng ký/Đăng nhập với JWT, lấy lại mật khẩu qua mã OTP.
* **Trải nghiệm Đặt vé (Real-time):** Lọc trận đấu, chọn ghế trực quan, giữ ghế tạm thời (Redis Lock), cập nhật trạng thái ghế ngay lập tức (WebSocket).
* **Thanh toán:** Tích hợp ví điện tử MoMo, tạo mã QR đơn hàng và xử lý IPN để chốt đơn tự động.
* **Trợ lý ảo:** Chatbot AI (RAG + LLaMA) giải đáp thắc mắc về trận đấu, giá vé, chính sách theo thời gian thực.
* **Quản lý cá nhân:** Theo dõi lịch sử đơn hàng, gửi yêu cầu đổi/trả vé, nhận vé điện tử (QR Code) qua Email.

---

## ⚙️ Hướng dẫn Cài đặt & Chạy dự án (Local Development)

**1. Clone Repository:**
```bash
git clone [https://github.com/dat060603/ticket-booking-be.git](https://github.com/dat060603/ticket-booking-be.git)
cd ticket-booking-be
2. Thiết lập môi trường ảo (Virtual Environment):
python -m venv env
source env/Scripts/activate  # (Với Windows) hoặc source env/bin/activate (Với MacOS/Linux)
pip install -r requirements.txt
3. Cấu hình biến môi trường (.env):
Tạo file .env ở thư mục gốc (ngang hàng với manage.py) và cung cấp các thông tin sau:
# Database (MySQL)
DB_NAME=your_db_name
DB_USER=your_db_user
DB_PASSWORD=your_db_password
DB_HOST=127.0.0.1
DB_PORT=3306

# Redis
REDIS_URL=redis://127.0.0.1:6379/1

# MoMo Payment Sandbox Configs
MOMO_PARTNER_CODE=your_partner_code
MOMO_ACCESS_KEY=your_access_key
MOMO_SECRET_KEY=your_secret_key

# AI / Email Services
GROQ_API_KEY=your_groq_api_key
EMAIL_HOST_USER=your_email@gmail.com
EMAIL_HOST_PASSWORD=your_app_password
4. Khởi tạo Database:
python manage.py makemigrations
python manage.py migrate
5. Chạy các Server:
Để hệ thống hoạt động đầy đủ tính năng, cần mở 3 Terminal khác nhau để chạy các tiến trình sau:
Terminal 1
python manage.py runserver
Terminal 2
celery -A ticket_booking worker --loglevel=info --pool=solo
Terminal 3
celery -A ticket_booking beat -l info
Tác giả
Triệu Quốc Đạt - Trưởng nhóm 
(Và cộng sự)
Đồ án tốt nghiệp thực hiện tại Học viện Công nghệ Bưu chính Viễn thông (Cơ sở TP.HCM).
