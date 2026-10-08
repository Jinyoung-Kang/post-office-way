# Next.js 16 (Pages Router, React 19, webpack 빌드 — ADR-022) — standalone 출력
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

FROM node:22-bookworm-slim AS build
WORKDIR /app
ARG API_INTERNAL_BASE=http://api:8100
ENV API_INTERNAL_BASE=$API_INTERNAL_BASE NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-bookworm-slim
WORKDIR /app
# API 프록시(pages/api/v1)가 실행 시점에 읽는 FastAPI 주소
ARG API_INTERNAL_BASE=http://api:8100
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3100 HOSTNAME=0.0.0.0 API_INTERNAL_BASE=$API_INTERNAL_BASE
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
EXPOSE 3100
CMD ["node", "server.js"]
