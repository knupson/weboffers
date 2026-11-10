FROM node:24-alpine
RUN apk add --no-cache git
WORKDIR /app
COPY deploy.mjs ./
# La cadena invoca deploy.mjs mediante docker exec; iniciar el contenedor no despliega.
CMD ["sleep", "infinity"]
