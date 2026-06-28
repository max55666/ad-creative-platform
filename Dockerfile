FROM node:22-bookworm-slim

ENV NEXT_TELEMETRY_DISABLED=1
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PNPM_HOME=/pnpm
ENV PATH="$PNPM_HOME:$PATH"

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates openssl ffmpeg \
  && rm -rf /var/lib/apt/lists/*

RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
RUN pnpm exec playwright install --with-deps chromium

COPY . .

RUN pnpm prisma generate
RUN pnpm build

EXPOSE 3000

CMD ["sh", "-c", "mkdir -p /app/public/uploads && pnpm prisma migrate deploy && pnpm start -- -H 0.0.0.0 -p ${PORT:-3000}"]
