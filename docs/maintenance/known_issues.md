---
title: "Known Issues"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Stakeholders", "Developers"]
---

| Severity | Issue | Impact | Workaround | Target Fix |
|---|---|---|---|---|
| medium | SMART callback URL differences across servers | OAuth errors during login | Verify `redirect_uri` and base URL logic | 0.2.0 |
| low | Missing logout session invalidation | Sessions may persist longer than desired | Manual session deletion in DB | 0.2.0 |


