# Hướng Dẫn Chạy Telegram Digital Shop Bot

File này hướng dẫn chạy bot Telegram và Web Admin Panel.

## 1. Yêu cầu

- Python 3.11+ hoặc Docker Desktop
- PostgreSQL
- Redis
- Telegram bot token từ BotFather

Web admin chạy mặc định tại:

```text
http://127.0.0.1:8000/login
```

## 2. Chuẩn bị `.env`

Copy file mẫu:

```powershell
Copy-Item .env.example .env
```

Mở `.env` và sửa các giá trị quan trọng:

```env
BOT_TOKEN=your_telegram_bot_token_here
ADMIN_IDS=123456789
ADMIN_PASSWORD=your_admin_web_password_here
SESSION_SECRET=replace_with_long_random_secret
SESSION_COOKIE_SECURE=false
WEB_HOST=0.0.0.0
WEB_PORT=8000
```

Nếu chạy bằng Docker Compose, giữ database/redis như mặc định:

```env
DATABASE_URL=postgresql+asyncpg://shopbot:shopbot_secret@db:5432/shopbot
REDIS_URL=redis://redis:6379/0
```

Nếu chạy local không Docker, đổi về host local:

```env
DATABASE_URL=postgresql+asyncpg://shopbot:shopbot_secret@localhost:5432/shopbot
REDIS_URL=redis://localhost:6379/0
```

## 3. Cách chạy nhanh bằng Docker Compose

Chạy toàn bộ bot + web + Postgres + Redis:

```powershell
docker compose up --build
```

Mở web admin:

```text
http://127.0.0.1:8000/login
```

Đăng nhập bằng `ADMIN_PASSWORD` trong `.env`.

Dừng app:

```powershell
docker compose down
```

Dừng app và xóa data database/redis:

```powershell
docker compose down -v
```

Cẩn thận: lệnh trên xóa dữ liệu Postgres và Redis.

## 4. Cách chạy local bằng Python

Tạo virtual environment:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

Cài dependencies:

```powershell
pip install -r requirements.txt
```

Cần có PostgreSQL và Redis đang chạy local trước khi chạy `python run.py`.

Sau đó chạy:

```powershell
python run.py
```

Khi chạy thành công sẽ thấy log dạng:

```text
Bot started
Web admin started at http://0.0.0.0:8000
```

Mở:

```text
http://127.0.0.1:8000/login
```

## 5. Kiểm tra nhanh sau khi chạy

Bot có persistent Telegram menu nằm cạnh ô nhập chat để khách mở nhanh mua hàng, đơn hàng, hỗ trợ và hướng dẫn.

- Vào `/login`, đăng nhập bằng `ADMIN_PASSWORD`.
- Vào `Sản Phẩm`, tạo sản phẩm mới.
- Vào `Nhập Kho`, nạp vài dòng digital goods.
- Tạo đơn từ Telegram bot.
- Vào `Đơn Hàng`, duyệt đơn và kiểm tra khách nhận key/account/link.
- Thử export CSV từ sidebar.

Kiểm tra nhanh UX Telegram:

- `/start` hiển thị persistent menu.
- Các nút menu hoạt động.
- `/shop`, `/orders`, `/help`, `/support` hoạt động.
- Luồng mua hàng hiển thị hướng dẫn thanh toán rõ ràng, polished.
- Tạo sản phẩm từ web admin thông báo sản phẩm mới tới người dùng.

## 6. Lệnh kiểm tra code

Compile toàn bộ app:

```powershell
python -m compileall app run.py
```

Nếu không có lỗi Python traceback là ổn.

## 7. Production notes

Trước khi public web admin:

- Đổi `ADMIN_PASSWORD` mạnh.
- Đổi `SESSION_SECRET` thành chuỗi random dài.
- Bật HTTPS qua reverse proxy.
- Set:

```env
SESSION_COOKIE_SECURE=true
```

- Không public trực tiếp port database/redis nếu deploy thật.
- Backup Postgres volume thường xuyên.
- Backup audit log tại `logs/admin_audit.jsonl`.

## 8. Lỗi thường gặp

### Không vào được web admin

Kiểm tra app có chạy port 8000 chưa:

```text
http://127.0.0.1:8000/login
```

Nếu đổi `WEB_PORT`, dùng port mới.

### Bot không phản hồi

Kiểm tra:

- `BOT_TOKEN` đúng.
- Bot không đang chạy ở nơi khác cùng token.
- Redis đang chạy.

### Database connection failed

Nếu chạy Docker Compose, `DATABASE_URL` phải dùng host `db`.

Nếu chạy local, `DATABASE_URL` phải dùng host `localhost`.

### Redis connection failed

Nếu chạy Docker Compose, `REDIS_URL` nên là:

```env
REDIS_URL=redis://redis:6379/0
```

Nếu chạy local:

```env
REDIS_URL=redis://localhost:6379/0
```
