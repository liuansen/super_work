# ==============================================================================
# Spider_XHS Multi-Stage Dockerfile
# ==============================================================================
# Stage 1: Build the frontend (React + Vite)
# Stage 2: Build Python wheels (compiler toolchain stays out of the runtime image)
# Stage 3: Runtime image with pre-built frontend + site-packages
#
# Usage:
#   docker build -t spider-xhs .
#   docker run -p 127.0.0.1:8000:8000 -e SECRET_KEY=... -v ./data:/app/data spider-xhs
# ==============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Frontend build
# ---------------------------------------------------------------------------
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

# Install dependencies first (layer caching); npm ci honours the lockfile
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

# Copy source and build
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Python dependencies (compiled in a throwaway stage)
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS python-deps

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# requirements-douyin.txt 提供抖音集成所需的 protobuf>=5.27 等依赖；
# 缺失时 RealDouyinAdapter 在容器内会因 ModuleNotFoundError 全部失效。
COPY requirements.txt requirements-douyin.txt ./
RUN pip install --prefix=/install -r requirements.txt -r requirements-douyin.txt

# ---------------------------------------------------------------------------
# Stage 3: Runtime
# ---------------------------------------------------------------------------
FROM python:3.11-slim-bookworm

WORKDIR /app

# Runtime system deps only: curl for HEALTHCHECK, libglib for OpenCV headless.
# 使用 opencv-python-headless（不链接 libGL/GUI），运行镜像不再需要 libgl1；
# 本项目只用到 imdecode/VideoCapture/imencode，headless 完全覆盖这些能力。
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js runtime (required for JS signature execution)
# 从官方镜像拷贝固定版本 Node（避免 curl | bash 执行远端脚本的供应链风险）
COPY --from=node:20-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=node:20-bookworm-slim /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && node --version && npm --version

# Python 依赖从构建阶段拷贝，运行镜像内不再保留 build-essential
COPY --from=python-deps /install /usr/local

# Install root-level Node.js deps first (layer caching: only invalidated by
# package.json/lockfile changes, not by source edits)
COPY package.json package-lock.json* ./
RUN if [ -f package.json ]; then \
        (npm ci --no-audit --no-fund --omit=dev || npm install --no-audit --no-fund --omit=dev); \
    fi

# Copy project source
COPY . .

# Copy pre-built frontend from Stage 1
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directory for SQLite and storage, and run as non-root
RUN mkdir -p /app/data /app/backend/app/storage/media /app/backend/app/storage/exports \
    && groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && chown -R app:app /app
USER app

# Set environment defaults
ENV PYTHONUNBUFFERED=1 \
    NODE_ENV=production \
    ENVIRONMENT=production \
    FRONTEND_SERVE_STATIC=true \
    CONFIG_FILE=/app/config/default.yaml

EXPOSE 8000

# Health check（INF-3：readiness 端点会实际探测数据库）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health/ready || exit 1

CMD ["python", "main.py", "--host", "0.0.0.0", "--port", "8000"]
