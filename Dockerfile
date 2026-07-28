FROM python:3.11-slim

WORKDIR /app

# Install system deps (including Playwright browser deps)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip procps curl \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 libxcomposite1 libxdamage1 \
    libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Install Playwright browser (chromium) for real headless browsing
RUN pip install playwright && \
    python -m playwright install chromium && \
    python -m playwright install-deps chromium 2>&1

ENV PLAYWRIGHT_BROWSERS_PATH=/root/.cache/ms-playwright

COPY . .

RUN mkdir -p data build_output

EXPOSE 8080
ENV DEPLOY=true

# Single worker with threads so agent threads stay in one process
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "8", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "dashboard_app:app"]
