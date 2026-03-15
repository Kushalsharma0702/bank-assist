# ─────────────────────────────────────────────────────────────────────────────
# Banking Voice Agent — Backend
# Target: AWS App Runner (port 8080)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim AS base

# System deps
#   ffmpeg      — pydub audio conversion
#   libssl-dev  — Azure Speech SDK
#   ca-certificates — HTTPS to Azure / AWS APIs
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        libssl-dev \
        libffi-dev \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python deps (cached layer) ────────────────────────────────────────────────
COPY requirements.txt .
# Step 1: upgrade pip
RUN pip install --no-cache-dir --upgrade pip

# Step 2: CPU-only PyTorch (avoids 4 GB CUDA build pulled by sentence-transformers)
RUN pip install --no-cache-dir --retries 5 --timeout 120 \
    torch --index-url https://download.pytorch.org/whl/cpu

# Step 3: remaining deps (cached separately from torch for faster rebuilds)
RUN pip install --no-cache-dir --retries 5 --timeout 120 -r requirements.txt

# ── Pre-download sentence-transformers model ──────────────────────────────────
# Baking the model into the image means zero download latency at startup.
# ~80 MB added to image size; worth it for a banking system.
RUN python -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('all-MiniLM-L6-v2'); \
print('Model pre-downloaded OK')"

# ── Application code ──────────────────────────────────────────────────────────
COPY . .

# ── Security: run as non-root ─────────────────────────────────────────────────
RUN useradd -m -u 1001 appuser \
 && chown -R appuser:appuser /app
USER appuser

# App Runner default port is 8080
EXPOSE 8080

# Health-check so App Runner / ALB knows the container is ready
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Sentence-transformers model is loaded at startup via FastAPI lifespan.
# --workers 1  keeps a single process so the model is only loaded once.
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--workers", "1", \
     "--log-level", "info"]
