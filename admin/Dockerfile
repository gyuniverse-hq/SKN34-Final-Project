FROM node:24-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build
FROM nginxinc/nginx-unprivileged:alpine
USER root
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
COPY runtime-config.template /opt/runtime-config.template
COPY start.sh /opt/start.sh
RUN chmod +x /opt/start.sh
USER 101
EXPOSE 8080
ENTRYPOINT ["/opt/start.sh"]
