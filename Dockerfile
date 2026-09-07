# Single-stage image targeting Cloud Run ($PORT binding)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first so the layer caches across source edits
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code (.dockerignore keeps .env and .venv out of the image)
COPY . .

# Cloud Run injects PORT; 8080 is the local default
ENV PORT=8080
EXPOSE 8080

# Streamlit must bind 0.0.0.0 and run headless behind Cloud Run's proxy
ENTRYPOINT ["sh", "-c", "streamlit run app/ui/app.py \
  --server.port=${PORT} \
  --server.address=0.0.0.0 \
  --server.headless=true \
  --server.enableCORS=false \
  --server.enableXsrfProtection=false \
  --browser.gatherUsageStats=false"]
