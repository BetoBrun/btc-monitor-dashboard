# Dockerfile for BTC Monitor Dashboard
# Deploy on Railway, Render, Fly.io

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .
COPY .env.example .env

ENV PORT=8080

EXPOSE 8080

CMD ["python", "dashboard_web.py"]