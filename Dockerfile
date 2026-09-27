FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Copy and install Python package
COPY pyproject.toml .
COPY src/ src/

RUN pip install --no-cache-dir -e ".[serve]"

# Create data dirs
RUN mkdir -p /app/data /app/.lm

# Copy fixture for demo
COPY tests/ tests/

EXPOSE 8000

CMD ["uvicorn", "lm.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
