FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
# npm install (not ci): the lock file is generated on Windows and lacks some Linux-only optional deps.
RUN npm install --no-audit --no-fund

COPY . .

ARG NEXT_PUBLIC_API_URL=http://localhost:8002
ARG NEXT_PUBLIC_ADMIN_URL=http://localhost:8003
ARG NEXT_PUBLIC_INGESTION_URL=http://localhost:8001
ARG INTERNAL_API_URL=http://localhost:8002
ARG INTERNAL_ADMIN_URL=http://localhost:8003
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_ADMIN_URL=$NEXT_PUBLIC_ADMIN_URL
ENV NEXT_PUBLIC_INGESTION_URL=$NEXT_PUBLIC_INGESTION_URL
ENV INTERNAL_API_URL=$INTERNAL_API_URL
ENV INTERNAL_ADMIN_URL=$INTERNAL_ADMIN_URL

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV PORT=3000
ENV NEXT_TELEMETRY_DISABLED=1
# Internal service URLs used by the server-side proxies. Defaults suit `docker run` next to a
# local stack; docker-compose overrides them with the service names (api:8000, admin:8000, …).
ENV INTERNAL_API_URL=http://localhost:8002
ENV INTERNAL_ADMIN_URL=http://localhost:8003
ENV INTERNAL_GOVERNANCE_URL=http://localhost:8004

# Run as the unprivileged `node` user that ships with the base image.
COPY --from=builder --chown=node:node /app/package*.json ./
COPY --from=builder --chown=node:node /app/.next ./.next
COPY --from=builder --chown=node:node /app/public ./public
COPY --from=builder --chown=node:node /app/node_modules ./node_modules
# Copy config so rewrites are re-evaluated at startup with runtime env vars
COPY --from=builder --chown=node:node /app/next.config.ts ./next.config.ts
USER node

EXPOSE 3000

CMD ["npm", "start"]
