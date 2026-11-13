FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/huggingface \
    TRANSFORMERS_CACHE=/opt/huggingface

WORKDIR /app

# Runtime libraries required by PyTorch / FAISS and a health-check utility.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    libstdc++6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install CPU-only PyTorch first to avoid pulling CUDA dependencies into the image.
RUN python -m pip install --upgrade pip && \
    python -m pip install --index-url https://download.pytorch.org/whl/cpu torch

COPY requirements.txt .
RUN python -m pip install -r requirements.txt

# Download the complete embedding model at image-build time. The application
# loads this local directory through BGEM3FlagModel(model_name, use_fp16=False).
# Change BGE_MODEL_ID and rebuild the image to upgrade/switch the model.
ARG BGE_MODEL_ID=BAAI/bge-m3
RUN mkdir -p /opt/models/bge-m3 && \
    python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='${BGE_MODEL_ID}', local_dir='/opt/models/bge-m3')"

# Prevent any Hugging Face network download at container runtime.
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

RUN mkdir -p /app/data/documents /app/data/extracted \
    /app/data/entity_resolution/indexes /app/data/entity_resolution/reports \
    /opt/huggingface

EXPOSE 8000

# Run schema migrations on every container start; Alembic applies only pending revisions.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
