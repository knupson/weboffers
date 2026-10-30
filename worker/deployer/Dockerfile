FROM node:22-alpine
RUN apk add --no-cache git
WORKDIR /app
COPY deploy.mjs ./
CMD ["node", "deploy.mjs"]
