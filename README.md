# Infrastructure AI Agent

A self-hosted, AI-powered infrastructure monitoring, troubleshooting, and self-healing platform.

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

- [ ] Build Alertmanager Webhook API
- [ ] Integrate Flowise with local Ollama
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
