# Build from the repository root: docker build -f web/Dockerfile .
# Two stages: Node is needed only to build the page, the final image is just a web server with static files.
FROM node:24-alpine AS build
WORKDIR /app
# Dependencies first: this layer is cached until the lock file changes
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ .
RUN npm run build

# The unprivileged variant runs as a normal user and listens on 8080
FROM nginxinc/nginx-unprivileged:stable-alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
