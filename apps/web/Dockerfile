FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

FROM nginx:1.27-alpine
# nginx sustituye ${API_UPSTREAM} en las plantillas de /etc/nginx/templates al arrancar
ENV API_UPSTREAM=http://api:8000
COPY apps/web/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 80
