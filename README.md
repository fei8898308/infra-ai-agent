# Infrastructure AI Agent

A self-hosted infrastructure alert analysis project. The first integration is
strictly read-only: **Alertmanager → FastAPI → Flowise → Ollama/Qwen3**.

## First integration

The authenticated `POST /webhooks/alertmanager` endpoint validates Alertmanager
v4 notifications, handles firing/resolved groups, suppresses recent duplicates,
and returns troubleshooting recommendations as text. It never executes model
output or changes infrastructure. **Dry-run is enabled by default**, so no alert
data reaches Flowise until an operator configures and reviews a tool-free flow.

Start in Ubuntu/WSL:

```bash
cd ~/infra-ai-agent
git branch --show-current  # feature/alertmanager-webhook
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest -q
python3 scripts/init_env.py  # creates private .env; refuses to overwrite it
docker compose config --quiet
docker compose up -d --build
.venv/bin/python scripts/send_alert.py
```

The Compose service joins the existing `/opt/agent-lab` network and listens at
`127.0.0.1:8088`; the lab stack must already be running. A first fixture submission
returns `status: dry_run`; a repeat within five minutes returns `duplicate`.

See the [setup and operating instructions](docs/setup.md),
[architecture and security boundaries](docs/architecture.md), and
[review notes](docs/review.md). The setup guide includes native Python testing,
Flowise/Qwen3 configuration, Alertmanager routing, retry behavior, and rollback.

## Project Overview

This project uses local LLMs to analyze infrastructure alerts, identify possible root causes, recommend troubleshooting actions, and eventually execute approved remediation workflows.

## Technology Stack

- **Flowise:** AI agent orchestration and workflows
- **Ollama / Qwen3:** Local LLM inference
- **FastAPI:** Alertmanager webhook receiver
- **PostgreSQL / pgvector:** Incident history and semantic memory
- **Prometheus / Alertmanager:** Infrastructure monitoring
- **Oxidized:** Network configuration history
- **Microsoft Teams:** Notifications and approvals
- **AWX:** Future controlled remediation

## Architecture

Prometheus → Alertmanager → FastAPI → Flowise → Ollama

Future integrations include PostgreSQL incident memory, read-only SSH validation, Teams notifications, and approved AWX remediation.

## Development Environments

- **LAB:** WSL2 / Proxmox testing
- **QA:** Pre-production validation
- **PROD:** Future controlled deployment

## Development Roadmap

- [x] Build authenticated Alertmanager webhook API with dry-run mode
- [x] Implement Flowise prediction client (live Qwen3 acceptance test pending)
- [ ] Implement incident storage
- [ ] Implement historical incident retrieval
- [ ] Connect Prometheus API
- [ ] Add read-only network validation
- [ ] Integrate Microsoft Teams
- [ ] Implement human approval workflows
- [ ] Implement controlled self-healing

## Security

The initial release is strictly read-only. No device configuration changes or automated remediation are permitted.

Credentials and environment-specific secrets must never be committed to GitHub.
