FROM python:3.10-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first (better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the app
COPY . .

# Expose port 7860 (required by HF)
EXPOSE 7860

# Better FastAPI/uvicorn command
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
