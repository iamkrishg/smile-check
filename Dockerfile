# Smile Check container (used by Azure Container Apps)
FROM python:3.13-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
EXPOSE 8000
# 2 workers, 90 s timeout because the AI check can take a few seconds
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "90", "app:app"]
