FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl git wget unzip build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Hermes Agent via pip (lighter than full shell installer)
RUN pip install --no-cache-dir git+https://github.com/NousResearch/hermes-agent.git

# Install our API dependencies
COPY hermes_hf/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy integration modules
COPY hermes_integration/ /app/hermes_integration/
COPY hermes_hf/app.py /app/app.py

# Export agent skills so Hermes has them at startup
RUN mkdir -p ~/.hermes/skills
COPY hermes_integration/agent_skills.py /app/
RUN python -c "from agent_skills import export_agent_skills; export_agent_skills(); print('Skills exported')" 2>/dev/null || true

ENV PYTHONPATH=/app
ENV PORT=7860

EXPOSE 7860

CMD ["python", "/app/app.py"]
