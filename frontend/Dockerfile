# Stage 1: Build dashboard SPA
FROM node:22-alpine AS dashboard-build
WORKDIR /app
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci
COPY dashboard/ ./
RUN npm run build

# Stage 2: Nginx serving widget + dashboard
FROM nginx:1.27-alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/styles.css /usr/share/nginx/html/styles.css
COPY frontend/script.js /usr/share/nginx/html/script.js

# Dashboard SPA from build stage
COPY --from=dashboard-build /app/dist/ /usr/share/nginx/dashboard/

EXPOSE 80

RUN apk add --no-cache curl

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://127.0.0.1/ || exit 1
