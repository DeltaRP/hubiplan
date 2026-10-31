# Entwicklungs-Container: Vite-Dev-Server mit Weiterleitung ans Backend.
# Für den Produktivbetrieb kommt später ein eigener Build (statische Dateien) dazu.
FROM node:24-alpine@sha256:8a32c8cf649a49915a66e81e7a609223c708d0adabf288ee3f4077d765542f85

WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci
COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
