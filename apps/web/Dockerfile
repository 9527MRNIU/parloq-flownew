FROM node:22-alpine AS development

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]

FROM development AS build
RUN npm run build

FROM nginx:1.28-alpine AS production
ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.title="Parloq Flow Web" \
      org.opencontainers.image.revision="${BUILD_VERSION}"
COPY nginx.production.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
