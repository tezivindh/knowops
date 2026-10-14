FROM node:22-alpine AS build
WORKDIR /build
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
COPY package*.json ./
COPY scripts/patch-braces.cjs ./scripts/patch-braces.cjs
RUN npm ci
COPY . .
RUN mkdir -p public && npm run build

# Preserve Next.js server rendering behind the Nginx entrypoint.
FROM node:22-alpine AS next-runtime
# The server needs Node, not npm/yarn or their package-management dependencies.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /opt/yarn* \
    /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/yarn* /usr/local/bin/corepack
RUN addgroup -g 10001 knowops && adduser -D -u 10001 -G knowops knowops
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3001 HOSTNAME=0.0.0.0
COPY --from=build --chown=10001:10001 /build/.next/standalone ./
COPY --from=build --chown=10001:10001 /build/.next/static ./.next/static
COPY --from=build --chown=10001:10001 /build/public ./public
USER 10001:10001
EXPOSE 3001
CMD ["node", "server.js"]

FROM nginxinc/nginx-unprivileged:stable-alpine AS runtime
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
ENV NEXT_UPSTREAM=next:3001 BACKEND_UPSTREAM=backend:8000
USER 101:101
EXPOSE 8080
