---
title: "Monitoring & Observability"
version: "0.1.0-draft"
last_updated: "2025-08-13"
owner: "OptiMed AI"
audiences: ["Developers", "SRE", "Stakeholders"]
---

## Executive Summary
Track availability, latency, and error rates. Use OpenTelemetry for traces, Prometheus for metrics, Grafana dashboards, and structured logs.

SLOs/SLIs
- Availability: 99.9%
- p95 latency: chat ≤ 2.5s, diagnose ≤ 4s
- Error rate: ≤ 1%

Alerting Policy
- Page on SLO burn or error spikes; ticket on sustained degradation.

Logging & Tracing
- Include request IDs, session, patient_id (pseudonymized), and user_id where appropriate.

Stakeholder Notes
- Ensure logs exclude sensitive payloads; use sampling and redaction.


