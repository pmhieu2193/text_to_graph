# Knowledge Graph - Document API (Day 1)

FastAPI module for uploading PDF documents and listing their metadata.

## Features

- PDF extension and file-signature validation
- Empty-file and maximum-size validation
- UUID-based stored filenames
- SHA-256 checksum
- SQLite metadata persistence with SQLAlchemy 2.x
- Document status and UTC upload timestamp
- Paginated document listing

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000/docs

## API

### Upload

`POST /api/v1/documents/upload`

Use `multipart/form-data`, field name: `file`.

### List

`GET /api/v1/documents?page=1&page_size=20`

### Detail

`GET /api/v1/documents/{document_id}`

### Health

`GET /health`

## Storage

- PDF files: `storage/documents/<uuid>.pdf`
- Metadata: `data/app.db`

The original filename is retained in SQLite. The physical filename is generated from a UUID to avoid collisions and path traversal.

## Initial status

Newly uploaded documents receive `UPLOADED`. Later pipeline stages can transition the status to `PENDING`, `PROCESSING`, `COMPLETED`, or `FAILED`.

## Notes

This is a small MVP implementation. The initial schema is created with SQLAlchemy `create_all`; introduce Alembic before making repeated schema changes or deploying persistent environments. For production, also add authentication, rate limits, malware scanning, retention rules, and stronger PDF parsing/validation.

# Vietnamese Knowledge Graph API — Day 2

Bổ sung trích xuất văn bản PDF và chunking vào project ngày 1.

## Chạy
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```
Swagger: http://127.0.0.1:8000/docs

## Lưu ý nâng cấp DB ngày 1
Ngày 2 thêm cột vào `documents`; `create_all()` không ALTER bảng cũ. Nếu DB ngày 1 chưa có dữ liệu cần giữ: dừng server, xóa `data/app.db`, chạy lại. Khi cần giữ dữ liệu, tạo Alembic migration thay vì xóa DB.

## API
- `POST /api/v1/documents/upload` — upload (ngày 1)
- `GET /api/v1/documents` — danh sách
- `GET /api/v1/documents/{id}` — chi tiết/trạng thái
- `POST /api/v1/documents/{id}/process` — trích xuất và tạo chunks
- `GET /api/v1/documents/{id}/chunks?page=1&page_size=20` — xem chunks

## Quy trình thử
1. Upload PDF lấy `id`.
2. Gọi `POST /api/v1/documents/{id}/process`.
3. Kiểm tra document status `COMPLETED` và `page_count`, `chunk_count`.
4. Gọi endpoint `/chunks` và xem file text ở `storage/extracted/<id>.txt`.

## Chunk mặc định
`CHUNK_SIZE=1000`, `CHUNK_OVERLAP=150` (đơn vị ký tự, không phải token). Cần tinh chỉnh sau khi đánh giá chất lượng extraction và context window của LLM.

## Giới hạn
- PDF scan chưa OCR; không có text layer sẽ `FAILED`.
- Chunk theo ký tự, chưa dùng tokenizer.
- Xử lý đang đồng bộ trong HTTP request, phù hợp MVP local; chưa phù hợp file lớn/nhiều người dùng đồng thời.
- Chưa gọi Gemini, embedding hoặc Neo4j.
- `page_start/page_end` là phạm vi trang có nội dung giao với chunk, chưa lưu bounding boxes.

## Ngày 3
Thiết kế schema Entity/Relation, gọi Gemini trả JSON có cấu trúc, validate bằng Pydantic và lưu raw extraction kèm `chunk_id` để truy vết nguồn.

