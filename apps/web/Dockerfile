# ───── Build stage ─────
FROM node:20-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Vite inlines VITE_* env vars at build time — pass them as build args
ARG VITE_API_URL
ARG VITE_WS_URL
ENV VITE_API_URL=${VITE_API_URL}
ENV VITE_WS_URL=${VITE_WS_URL}

RUN npm run build

# ───── Runtime stage ─────
FROM nginx:1.27-alpine

# Template (with ${PORT}) is auto-processed by nginx image entrypoint on boot.
# Default PORT=80; Railway will override with its injected value.
ENV PORT=80
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -q --spider "http://localhost:${PORT}/" || exit 1

CMD ["nginx", "-g", "daemon off;"]
