FROM python:3.10-slim

# Install system dependencies for PDF + DOC extraction
RUN apt-get update && apt-get install -y \
    build-essential \
    poppler-utils \
    antiword \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy rest of your application
COPY . .

EXPOSE 7860

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
