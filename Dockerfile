# Base image
FROM python:3.10-slim

# Install dependencies
RUN apt-get update && apt-get install -y \
    wget gnupg2 curl unzip \
    fonts-liberation libatk-bridge2.0-0 libatk1.0-0 \
    libgtk-3-0 libgbm1 libnss3 libxss1 libasound2 libx11-xcb1 \
    libxcomposite1 libxdamage1 libxrandr2 libappindicator3-1 \
    libu2f-udev xdg-utils libdrm2 lsb-release \
    chromium chromium-driver && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CHROMIUM_PATH=/usr/bin/chromium

# Create working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 5005

# Start app
CMD ["uvicorn", "app_camera:app", "--host", "0.0.0.0", "--port", "5005"]
