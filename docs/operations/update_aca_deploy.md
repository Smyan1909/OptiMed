---
title: "Update & Deploy on Azure Container Apps (ACA)"
version: "0.1.0"
last_updated: "2025-09-06"
owner: "OptiMed AI"
audiences: ["Developers", "SRE"]
---

## Scope
- Backend: FastAPI (`src/optimed/apps/api_gateway`), containerized via `Dockerfile.backend` and `requirements.txt`.
- Frontend: Next.js app at `src/optimed/apps/web`.
- Registry: Azure Container Registry (ACR).
- Runtime: Azure Container Apps (ACA) with external ingress.
- Database: Azure Database for PostgreSQL Flexible Server with `pgvector`.

## Prerequisites
- Azure CLI logged in: `az login`
- Resource group and names exported in PowerShell:
```
$RG = "OPTIMED"
$LOCATION = "northeurope"
$ACR = "optimedacr123"
$BACKEND_APP = "optimed-backend"
$FRONTEND_APP = "optimed-web"
$BACKEND_IMAGE = "$ACR.azurecr.io/optimed-backend"
$FRONTEND_IMAGE = "$ACR.azurecr.io/optimed-web"
$TAG = (Get-Date -Format "yyyyMMdd-HHmmss")
```
- Ensure container apps already exist and ingress is enabled (backend target port 8000, frontend port 3000). If not, see docs/operations/setup_guide.md.

## Backend: Build and Deploy
1) Build backend image in ACR (server-side build):
```
az acr build -r $ACR -t "optimed-backend:$TAG" -f Dockerfile.backend .
```
2) Update image on Container App and keep external ingress:
```
az containerapp update -g $RG -n $BACKEND_APP --image "$BACKEND_IMAGE:$TAG"
az containerapp ingress enable -g $RG -n $BACKEND_APP --type external --target-port 8000 --transport auto
```
3) Set or update environment variables (examples):
```
# Secrets first (recommended):
az containerapp secret set -g $RG -n $BACKEND_APP --secrets "OPENAI_API_KEY=$env:OPENAI_API_KEY" "ANTHROPIC_API_KEY=$env:ANTHROPIC_API_KEY"

# Env vars referencing secrets and config:
az containerapp update -g $RG -n $BACKEND_APP --set-env-vars \
  "OPENAI_API_KEY=secretref:OPENAI_API_KEY" \
  "ANTHROPIC_API_KEY=secretref:ANTHROPIC_API_KEY" \
  "PGVECTOR_DSN=$env:PGVECTOR_DSN" \
  "HF_HOME=/app/hf-cache" \
  "TRANSFORMERS_CACHE=/app/hf-cache" \
  "SENTENCE_TRANSFORMERS_HOME=/app/hf-cache"
```
4) Verify health and logs:
```
az containerapp show -g $RG -n $BACKEND_APP --query properties.configuration.ingress.fqdn -o tsv
az containerapp logs show -g $RG -n $BACKEND_APP --follow
```
Backend exposes `GET /health` and should return `{ "status": "ok" }`.

## Frontend: Build and Deploy
1) Build web image in ACR from the app Dockerfile:
```
az acr build -r $ACR -t "optimed-web:$TAG" -f src/optimed/apps/web/Dockerfile src/optimed/apps/web
```
2) Update image on Container App and keep external ingress:
```
az containerapp update -g $RG -n $FRONTEND_APP --image "$FRONTEND_IMAGE:$TAG"
az containerapp ingress enable -g $RG -n $FRONTEND_APP --type external --target-port 3000 --transport auto
```
3) (Optional) Env vars for frontend (e.g., API base URL):
```
az containerapp update -g $RG -n $FRONTEND_APP --set-env-vars \
  "NEXT_PUBLIC_API_BASE=https://$(az containerapp show -g $RG -n $BACKEND_APP --query properties.configuration.ingress.fqdn -o tsv)"
```
4) Check logs:
```
az containerapp logs show -g $RG -n $FRONTEND_APP --follow
```

## Config-only Changes
- Secrets: `az containerapp secret set -g $RG -n <app> --secrets KEY=VALUE [KEY2=VALUE2]`
- Env vars: `az containerapp update -g $RG -n <app> --set-env-vars KEY=VALUE [KEY2=VALUE2]`
- Ingress target port: `az containerapp ingress enable -g $RG -n <app> --type external --target-port <port> --transport auto`

## Hugging Face Models: Internet vs. Offline
- Option A: Allow runtime internet access (simplest). Do NOT set `TRANSFORMERS_OFFLINE=1`. The model will download on first run into `/app/hf-cache`.
- Option B: Bake model into the image (offline at runtime). Ensure `Dockerfile.backend` contains:
```
# Pre-download embedding model
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"
```
Keep env vars pointing caches to `/app/hf-cache`. If offline, ensure the above run step succeeds during ACR build.

## Rollback
1) List previous revisions:
```
az containerapp revision list -g $RG -n $BACKEND_APP -o table
```
2) Activate a previous revision by image tag or set image back:
```
az containerapp update -g $RG -n $BACKEND_APP --image "$BACKEND_IMAGE:<previousTag>"
```
3) Repeat for frontend if needed.

## Troubleshooting
- ACR build fails with Windows/Conda paths: ensure `requirements.txt` has only pip-compatible packages (no `pywin32`, no `@ file:///...`).
- Container exits with code 127: ensure backend `CMD` uses `python -m uvicorn ...` (already in `Dockerfile.backend`).
- `python-multipart` missing: ensure it is listed in `requirements.txt` and installed.
- HF cache offline error: either allow internet at runtime or bake the model at build as above.
- Container app ingress port ignored: use `az containerapp ingress enable ... --target-port <port>` instead of `az containerapp update` for port changes.
- View structured logs:
```
az containerapp logs show -g $RG -n <app> --follow
```

## Updating in the Future
- Repeat the build step with a new `$TAG` and update the app image.
- For small config changes, only update secrets/env vars; no rebuild needed.
- Keep images tagged by timestamp for easy rollback.
