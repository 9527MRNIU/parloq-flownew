FROM node:22-alpine AS development

WORKDIR /app
COPY package*.json ./
COPY vendor/thumbmarkjs/thumbmarkjs-thumbmarkjs-1.10.1.tgz ./vendor/thumbmarkjs/
COPY vendor/country-flag-icons/country-flag-icons-1.6.20.tgz ./vendor/country-flag-icons/
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
ENV NGINX_ENVSUBST_FILTER="^MANAGEMENT_HOST$"
COPY nginx.production.conf /etc/nginx/templates/default.conf.template
COPY management-origin.envsh /docker-entrypoint.d/15-management-origin.envsh
RUN chmod 755 /docker-entrypoint.d/15-management-origin.envsh
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
