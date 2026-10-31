# Baut das Frontend und liefert es zusammen mit Caddy aus.
# Build-Kontext ist das Wurzelverzeichnis des Repos.
FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85 AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM caddy:2-alpine@sha256:eb4d35b7452d1ab6171fbdbe8d9275b2301dad6dad92115d91e19fb9b24d510f
COPY deploy/Caddyfile deploy/Caddyfile.proxy /etc/caddy/
COPY deploy/caddy/ /etc/caddy/caddy/
COPY --from=build /app/dist /srv
COPY LICENSE /srv/lizenzen/LICENSE.txt
