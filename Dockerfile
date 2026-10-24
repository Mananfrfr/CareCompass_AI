# Runs all three CareCompass agents (coordinator in Agentverse mailbox mode by default).
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY scripts ./scripts
COPY data/fixtures ./data/fixtures
COPY data/catalog ./data/catalog
COPY data/insurer_networks ./data/insurer_networks
COPY docs/AGENT_PROFILE.md ./docs/AGENT_PROFILE.md
# Seeds, ASI1 key etc. are supplied at runtime: docker run --env-file .env -p 8000:8000 -v carecompass-data:/app/data carecompass
EXPOSE 8000
CMD ["python", "scripts/run_agents.py"]
