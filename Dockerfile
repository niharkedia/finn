FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY seed seed
COPY finn finn
COPY web web
# /tmp is writable on every free host (e.g. Hugging Face Spaces runs as a non-root user); the cache rebuilds itself.
ENV PYTHONUNBUFFERED=1 FINN_DB=/tmp/finn.db
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn finn.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
