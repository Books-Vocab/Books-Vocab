FROM python:3.12-slim

# 設定工作目錄
WORKDIR /app

# 設定環境變數
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    # 預設把資料庫跟設定檔放在 /app/data 底下，方便掛載 Volume
    KG_DATA_DIR=/app/data

# 安裝系統層級相依套件 (如果未來有需要編譯套件的話)
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 複製依賴檔並安裝 (利用 uv 會更快，這邊使用標準 pip，如果系統有 uv 可以替換)
# 這裡我們只複製 pyproject.toml 讓它能解析安裝
COPY pyproject.toml /app/

# 利用 pip 安裝 pyproject.toml 中的 dependencies
RUN pip install --no-cache-dir "uvicorn[standard]"
RUN pip install --no-cache-dir pytest pytest-asyncio
RUN pip install --no-cache-dir .

# 複製原始碼與靜態頁面
COPY src /app/src
COPY tests /app/tests
COPY pytest.ini /app/
COPY privacy.html /app/
COPY support.html /app/
COPY terms.html /app/
COPY guide.html /app/

# 建立資料夾
RUN mkdir -p /app/data

# 暴露 FastAPI 預設 port
EXPOSE 8000

# 啟動指令 (使用生產環境的設定，關閉 reload)
CMD ["uvicorn", "kg.api:app", "--host", "0.0.0.0", "--port", "8000"]
