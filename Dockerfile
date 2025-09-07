# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY kite_websocket.py .
COPY run_trading_bot.py .
COPY get_access_token.py .

# Make scripts executable
RUN chmod +x run_trading_bot.py

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser
RUN chown -R appuser:appuser /app
USER appuser

# Expose port (if needed for health checks)
EXPOSE 8080

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import psutil; exit(0 if any('kite_websocket.py' in ' '.join(p.cmdline()) for p in psutil.process_iter()) else 1)" || exit 1

# Default command
ENTRYPOINT ["python", "run_trading_bot.py"]
