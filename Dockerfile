# Image de production : API FastAPI + frontend + agent IA (le serveur MCP tourne en sous-processus).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# Utilisateur non-root ; data/ doit rester inscriptible pour tickets.json
RUN useradd --create-home app && mkdir -p data && chown -R app /app
USER app

EXPOSE 8000
CMD ["python", "api_server.py"]
