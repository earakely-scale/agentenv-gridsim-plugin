# GridSimEnv article: an Astro site built from tfrere's research-article-template, served by nginx on port 8080.
FROM node:20-slim

RUN apt-get update && apt-get install -y --no-install-recommends nginx && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY app/package*.json ./
RUN npm ci --no-audit --no-fund

COPY app/ .
# The embeds read /data/<file>; the data lives in src/content/assets/data (a symlink in the repo, a copy here).
RUN set -e; rm -rf public/data; mkdir -p public/data; cp -a src/content/assets/data/. public/data/; npm run build

COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && \
    mkdir -p /var/cache/nginx /var/run /var/log/nginx /var/lib/nginx/body && \
    chmod -R 777 /var/cache/nginx /var/run /var/log/nginx /var/lib/nginx /etc/nginx/nginx.conf /app

EXPOSE 8080
ENTRYPOINT ["/entrypoint.sh"]
