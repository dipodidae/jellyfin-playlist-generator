# Stage 1: Build Nuxt static files
FROM node:22-alpine AS frontend-builder

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

COPY frontend/ .
RUN pnpm generate

# Stage 2: Python + nginx runtime
FROM python:3.12-slim

WORKDIR /app

# Install tini, nginx, and apache2-utils (for htpasswd)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tini \
    nginx \
    apache2-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy Python requirements and install
COPY service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend code
COPY service/ .

# Copy static frontend from builder
COPY --from=frontend-builder /app/.output/public /app/static

# Copy nginx config
COPY nginx/app.conf /etc/nginx/sites-available/default

# Copy entrypoint
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Configure nginx to log to stdout/stderr
RUN ln -sf /dev/stdout /var/log/nginx/access.log \
    && ln -sf /dev/stderr /var/log/nginx/error.log

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

EXPOSE 80

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["/docker-entrypoint.sh"]
