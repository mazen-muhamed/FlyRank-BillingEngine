FROM python:3.11-slim

WORKDIR /app

# System deps for psycopg2/build + minimal runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# Runs the FastAPI app. The Celery worker + Redis run separately (see README).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
