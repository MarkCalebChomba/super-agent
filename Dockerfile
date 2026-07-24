FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip procps \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .
RUN mkdir -p data build_output && chmod +x start.sh entrypoint.sh

ENV DEPLOY=true
EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "dashboard_app:app"]
