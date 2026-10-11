# Build from the repository root: docker build -f web/Dockerfile --build-arg BENCH_IMAGE=<the bench image> .
# Node is needed only to build the page: the final image is just a web server with static files.
ARG BENCH_IMAGE
FROM ${BENCH_IMAGE} AS bench

FROM node:24-alpine AS build
WORKDIR /app
# Dependencies first: this layer is cached until the lock file changes
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ .
RUN npm run build

# The unprivileged variant runs as a normal user and listens on 8080
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
# The pictures the pipelines are measured on, taken from the bench image itself:
# the page shows exactly what the models see
COPY --from=bench /opt/bench/public /usr/share/nginx/html/samples
EXPOSE 8080
