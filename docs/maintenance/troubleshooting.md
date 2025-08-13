---
title: "Troubleshooting"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers", "Support"]
---

## Common Issues
- API 401 on DICOM routes: missing `X-Session-ID` or expired session.
- SMART login fails: invalid redirect URI or token endpoint URL.
- Chat slow: LLM latency or vector DB contention; check traces.

Runbooks
- Clear chat history for a patient: `DELETE /patients/{id}/chat-history`.
- Check current repository status: `GET /status/repository`.


