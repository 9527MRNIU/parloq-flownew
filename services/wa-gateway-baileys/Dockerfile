FROM node:22-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
COPY vendor/baileys/whiskeysockets-baileys-6.7.24.tgz ./vendor/baileys/
COPY vendor/libsignal/libsignal-6.0.0.tgz ./vendor/libsignal/
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-bookworm-slim
ARG BUILD_VERSION=dev
LABEL org.opencontainers.image.title="Parloq Flow Baileys Gateway" \
      org.opencontainers.image.revision="${BUILD_VERSION}"
ENV NODE_ENV=production
WORKDIR /app
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER node
EXPOSE 8010
CMD ["node", "dist/index.js"]
