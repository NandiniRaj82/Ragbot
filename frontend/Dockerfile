FROM node:20-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

# Railway injects this as a build-time variable (default to the production backend URL)
ARG NEXT_PUBLIC_API_URL=https://ragbot-production-f48d.up.railway.app
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

RUN npm run build
# Ensure public dir exists even if empty
RUN mkdir -p /app/public

# ---- Production image ----
FROM node:20-alpine AS runner

WORKDIR /app
ENV NODE_ENV=production
ENV BACKEND_URL=https://ragbot-production-f48d.up.railway.app

COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

ENV HOSTNAME="0.0.0.0"
ENV PORT=3000
EXPOSE ${PORT}

CMD ["node", "server.js"]
