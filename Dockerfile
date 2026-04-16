FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow, psycopg2, spatial libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libjpeg-dev zlib1g-dev libgdal-dev \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Create dirs
RUN mkdir -p uploads reports instance

# Production settings
ENV FLASK_DEBUG=0
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Default: Strecker site (use SITE env var to switch)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", \
     "--workers", "1", \
     "--timeout", "60", \
     "--max-requests", "200", "--max-requests-jitter", "20", \
     "wsgi:app"]
