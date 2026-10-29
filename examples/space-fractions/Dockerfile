# Headless server mode (REST API). The desktop app is built with `npm run dist`.
FROM node:18.20-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev --no-audit --no-fund
COPY src ./src
COPY public ./public
ENV PORT=3000
EXPOSE 3000
CMD ["node", "src/server.js"]
