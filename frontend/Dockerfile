# Stage 1: Build dashboard SPA
FROM node:24-alpine AS dashboard-build
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# Stage 2: Nginx serving dashboard
FROM nginx:1.27-alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf

# Dashboard SPA at root
COPY --from=dashboard-build /app/dist/ /usr/share/nginx/html/

# Widget loader script (served as static file with CORS *)
COPY frontend/widget-loader.js /usr/share/nginx/html/widget-loader.js

EXPOSE 80

RUN apk add --no-cache curl

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1/ || exit 1
