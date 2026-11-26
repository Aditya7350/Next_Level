# Stage 1: Build React Frontend
FROM node:20-slim AS frontend-builder
WORKDIR /app/Frontend
COPY Frontend/package*.json ./
RUN npm install
COPY Frontend/ ./
RUN npm run build

# Stage 2: Python Backend Runtime
FROM python:3.12-slim
WORKDIR /app

# Install system runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application, weights, and compiled frontend assets
COPY backend/ ./backend/
COPY yolo11n.pt ./yolo11n.pt
COPY --from=frontend-builder /app/Frontend/dist ./Frontend/dist

# Render automatically sets PORT environment variable
ENV PORT=8000
EXPOSE 8000

# Start server
CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
