FROM node:20-alpine
WORKDIR /app
COPY package.json package-lock.json* /app/
RUN npm ci && chmod +x node_modules/.bin/next
# pass-through for build-time env
ARG NEXT_PUBLIC_DEFAULT_FHIR_SERVER
ENV NEXT_PUBLIC_DEFAULT_FHIR_SERVER=${NEXT_PUBLIC_DEFAULT_FHIR_SERVER}
ARG FRONTEND_URL
ENV FRONTEND_URL=${FRONTEND_URL}
COPY . /app
RUN npm run build
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
EXPOSE 3000
CMD ["npm","run","start"]
