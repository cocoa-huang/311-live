FROM node:22-slim AS deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM node:22-slim AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE_URL=
ARG NEXT_PUBLIC_WS_BASE_URL=
ARG NEXT_PUBLIC_REAL_LOCATION_MODE=false
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_WS_BASE_URL=${NEXT_PUBLIC_WS_BASE_URL} \
    NEXT_PUBLIC_REAL_LOCATION_MODE=${NEXT_PUBLIC_REAL_LOCATION_MODE}
COPY --from=deps /app/node_modules ./node_modules
COPY frontend ./
RUN npm run build

FROM node:22-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    PORT=8080
COPY --from=build /app ./
EXPOSE 8080
CMD ["sh", "-c", "npm run start -- -H 0.0.0.0 -p ${PORT}"]
