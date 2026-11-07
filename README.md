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
