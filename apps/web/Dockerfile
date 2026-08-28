FROM node:20-slim AS builder

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

WORKDIR /workspace

RUN corepack enable

COPY pnpm-workspace.yaml package.json pnpm-lock.yaml ./

COPY apps/web/package.json ./apps/web/

RUN pnpm install --frozen-lockfile --filter ./apps/web...

COPY apps/web ./apps/web
WORKDIR /workspace/apps/web
RUN pnpm build


FROM nginx:alpine

RUN rm -rf /usr/share/nginx/html/*

COPY --from=builder /workspace/apps/web/dist /usr/share/nginx/html

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]