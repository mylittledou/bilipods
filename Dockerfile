FROM python:3.11-slim

# Install ffmpeg and system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source files
COPY backend /app/backend
COPY frontend /app/frontend
COPY main.py /app/main.py

# Create downloads directory
RUN mkdir -p /app/downloads

EXPOSE 8000

ENV PYTHONUNBUFFERED=1

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
