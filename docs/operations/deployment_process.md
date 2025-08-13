---
title: "Deployment Process"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers", "SRE"]
---

## Executive Summary
CI/CD via GitHub Actions builds, tests, and deploys to dev/stage/prod. Use blue/green or canary, with rollbacks via previous image tags and DB migrations gated.

Pipelines
- Build & Test → Security scan → Package images → Deploy dev → Promote stage → Manual approval → Deploy prod.

Secrets Management
- Managed via cloud secret manager (e.g., Azure Key Vault) or SOPS; never committed.

Rollbacks
- Use previous container image and revert migrations; ensure data backups are valid.

Stakeholder Notes
- Keep change approvals and audit logs for regulated environments.


