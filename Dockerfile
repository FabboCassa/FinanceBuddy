# Use official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Persisted HuggingFace cache (mounted as a Docker volume in compose) so FinBERT
# weights are downloaded once and survive container restarts.
ENV HF_HOME=/models/huggingface

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    gcc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# Copy project files
COPY . /app/

# Normalize line endings (in case of CRLF on Windows hosts) and make executable.
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Create the HuggingFace cache mount point.
RUN mkdir -p /models/huggingface

# Expose port 8000
EXPOSE 8000

# Entrypoint handles DB wait + migrations + bootstrap; CMD is the service command.
ENTRYPOINT ["/app/entrypoint.sh"]

# Command is overridden in docker-compose.yml
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
