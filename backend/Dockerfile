# === Builder stage ===
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

# === Runtime stage ===
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    KG_DATA_DIR=/app/data

WORKDIR /app

# 只複製已安裝的 packages
COPY --from=builder /install /usr/local

# 複製應用程式碼
COPY src/ src/
COPY privacy.html support.html terms.html guide.html ./

# 非 root 用戶（UID 1000 匹配 host ubuntu 預設）
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs')" || exit 1

CMD ["uvicorn", "kg.api:app", "--host", "0.0.0.0", "--port", "8000"]
