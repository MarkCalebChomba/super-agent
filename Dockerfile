FROM python:3.11-slim

WORKDIR /app

# System deps for browser automation + psutil
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    unzip \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p data

EXPOSE 8080

# Deploy mode: starts agent system + health server for cron-job.org pings
ENV DEPLOY=true
CMD ["python", "main.py", "--deploy"]
