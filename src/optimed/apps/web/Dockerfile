FROM node:20-alpine
WORKDIR /app

# Install dependencies
COPY package.json package-lock.json* /app/
RUN npm ci && chmod +x node_modules/.bin/next

# Copy source files
COPY . /app

# Build-time environment variables
ARG NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_DEFAULT_FHIR_SERVER
ARG NEXT_PUBLIC_INFO_MODE
ARG NEXT_PUBLIC_ENABLE_STANDARD_LOGIN
ARG FRONTEND_URL
ARG API_BASE_URL

ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}
ENV NEXT_PUBLIC_DEFAULT_FHIR_SERVER=${NEXT_PUBLIC_DEFAULT_FHIR_SERVER}
ENV NEXT_PUBLIC_INFO_MODE=${NEXT_PUBLIC_INFO_MODE}
ENV NEXT_PUBLIC_ENABLE_STANDARD_LOGIN=${NEXT_PUBLIC_ENABLE_STANDARD_LOGIN}
ENV FRONTEND_URL=${FRONTEND_URL}
ENV API_BASE_URL=${API_BASE_URL}

# Debug environment variables
RUN echo "=== Build Environment Debug ===" && \
    echo "NEXT_PUBLIC_API_BASE_URL: ${NEXT_PUBLIC_API_BASE_URL}" && \
    echo "NEXT_PUBLIC_DEFAULT_FHIR_SERVER: ${NEXT_PUBLIC_DEFAULT_FHIR_SERVER}" && \
    echo "NEXT_PUBLIC_INFO_MODE: ${NEXT_PUBLIC_INFO_MODE}" && \
    echo "NEXT_PUBLIC_ENABLE_STANDARD_LOGIN: ${NEXT_PUBLIC_ENABLE_STANDARD_LOGIN}" && \
    echo "FRONTEND_URL: ${FRONTEND_URL}" && \
    echo "API_BASE_URL: ${API_BASE_URL}" && \
    echo "================================"

# Override .env.production with build args if they're provided
RUN if [ -n "$NEXT_PUBLIC_API_BASE_URL" ]; then \
        echo "Overriding .env.production with build args..." && \
        echo "# Build-time environment variables from Docker build args" > .env.production && \
        echo "NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL}" >> .env.production && \
        echo "NEXT_PUBLIC_DEFAULT_FHIR_SERVER=${NEXT_PUBLIC_DEFAULT_FHIR_SERVER}" >> .env.production && \
        echo "NEXT_PUBLIC_INFO_MODE=${NEXT_PUBLIC_INFO_MODE}" >> .env.production && \
        echo "NEXT_PUBLIC_ENABLE_STANDARD_LOGIN=${NEXT_PUBLIC_ENABLE_STANDARD_LOGIN}" >> .env.production && \
        echo "FRONTEND_URL=${FRONTEND_URL}" >> .env.production && \
        echo "API_BASE_URL=${API_BASE_URL}" >> .env.production && \
        echo "Generated .env.production:" && \
        cat .env.production; \
    else \
        echo "Using existing .env.production file" && \
        cat .env.production; \
    fi

# Build the application
RUN npm run build
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000
EXPOSE 3000
CMD ["npm","run","start"]
