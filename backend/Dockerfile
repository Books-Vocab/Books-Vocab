# === Builder stage ===
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 依 uv.lock 安裝（#2088）：`uv export --locked` 在 lock 落後 pyproject.toml 時直接失敗；
# pip `--no-deps --require-hashes` 只裝清單內、雜湊相符的版本，build 時不再重新解析。
# pytest／pytest-asyncio 刻意保留（lock 版本）：/admin/tests 在容器內跑 pytest
# （src/kg/admin_test_matrix/runner.py）；其餘 dev 工具不進 image。uv 版本對齊 CI。
# 驗證：scripts/check_image_lock.py（backend-quality workflow 的 image-lock job）。
COPY pyproject.toml uv.lock ./
RUN pip install --no-cache-dir uv==0.8.23 \
    && uv export --locked --no-emit-project --format requirements-txt -o requirements.txt \
       --no-emit-package ruff --no-emit-package pytest-cov --no-emit-package coverage \
    && pip install --no-cache-dir --prefix=/install --no-deps --require-hashes -r requirements.txt

# === Runtime stage ===
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    KG_DATA_DIR=/app/data

WORKDIR /app

# 只複製已安裝的 packages
COPY --from=builder /install /usr/local

# 複製應用程式碼
COPY src/ src/
COPY tests/ tests/
COPY pytest.ini ./
COPY index.html privacy.html support.html terms.html guide.html ./
COPY static/ static/
COPY ops_cli.py ops_analyze.py ops_edit.py ./

# 非 root 用戶（UID 1000 匹配 host ubuntu 預設）
RUN useradd --create-home --shell /bin/bash --uid 1000 appuser \
    && mkdir -p /app/data \
    && chown appuser:appuser /app/data
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD timeout 4 python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/docs', timeout=3)" || exit 1

# --workers 1 是硬性不變式，勿改：quota_service._reservations 等 process-local
# state 不跨 worker 共享，多 worker 會導致額度 over-spend。詳見 docs/dev/deploy.md。
CMD ["uvicorn", "kg.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
