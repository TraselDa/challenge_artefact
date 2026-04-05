# -----------------------------------------------------------------------------
# Stage 1 : Builder
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Increase pip timeout and retries for slow/flaky network during build
ENV PIP_DEFAULT_TIMEOUT=300
ENV PIP_RETRIES=10

COPY requirements.txt .

# Install PyTorch CPU-only FIRST so sentence-transformers doesn't pull the GPU variant
RUN pip install --no-cache-dir torch \
    --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2 : Runner
# -----------------------------------------------------------------------------
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY src/ ./src/
COPY data/reference/ ./data/reference/
COPY scripts/ ./scripts/

RUN mkdir -p data/raw data/processed

EXPOSE 8000 8501

CMD uvicorn src.api.main:app --host 0.0.0.0 --port 8000 & \
    streamlit run src/app/streamlit_app.py --server.port 8501 --server.address 0.0.0.0 & \
    wait
