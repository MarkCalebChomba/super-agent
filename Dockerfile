FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget unzip procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

RUN mkdir -p data build_output

EXPOSE 8080

ENV DEPLOY=true

# Railway deploy: serve the Flask dashboard (agents run on user's machine)
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "2", "--threads", "4", "dashboard_app:app", "--timeout", "120"]
