# Dashboard Frontend — Vite + React build served by Nginx
# Multi-stage: build with Node 18, serve with nginx:alpine

# ── Stage 1: build ──────────────────────────────────────────────────────────
FROM node:18-alpine AS builder

WORKDIR /app

# Install dependencies first (cache layer)
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm install

# Copy source
COPY dashboard/ .

# Build static assets
RUN npm run build

# ── Stage 2: serve ──────────────────────────────────────────────────────────
FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# SPA routing — redirect 404s to index.html
RUN printf 'server {\n  listen 3000;\n  root /usr/share/nginx/html;\n  index index.html;\n  location / {\n    try_files $uri $uri/ /index.html;\n  }\n}\n' \
    > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
