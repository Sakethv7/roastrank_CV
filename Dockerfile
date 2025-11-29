FROM python:3.10-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your Flask app and all files
COPY . .

# Create instance directory for SQLite database
RUN mkdir -p instance

# Expose port 7860 (Hugging Face Spaces requirement)
EXPOSE 7860

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Run the Flask app on port 7860
CMD ["python", "main.py"]