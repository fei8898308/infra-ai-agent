# Review notes: first Alertmanager integration

Branch: `feature/alertmanager-webhook`, based on `eb52539`.
Changes are prepared locally for review; no merge or production activation is
part of this implementation.

## Result

Alertmanager v4 groups can be delivered to an authenticated FastAPI endpoint.
Dry-run validates and acknowledges them without model calls. After an operator
reviews a dedicated tool-free Flowise/Qwen3 chatflow and configures its API key,
live analysis sends selected evidence to that flow and returns text advice.
Both firing and resolved states are supported. Recent successful duplicates
are suppressed, and upstream failure remains retryable.

Included: bounded validation, fail-closed configuration, sanitized error/log
handling, Flowise client, synthetic fixture, unit tests, container integration
test, CI workflow, private environment initializer, fixture client, hardened
Dockerfile, Compose connection to the existing lab network, Alertmanager example,
architecture notes, and setup/rollback instructions.

## Local validation — 2026-11-02

- Python 3.12 unit suite: **56 passed**. Coverage includes authentication, dry-run
  isolation, schema/bounds, data selection, prediction request shape, duplicate
  and resolved events, overload/in-flight races, TTL/eviction, upstream errors,
  redirects, timeouts, response limits, retryability, and secret handling.
- Ruff lint and formatting checks passed; Git whitespace checks passed.
- Runtime pinned dependencies: `pip-audit` reported **no known vulnerabilities**.
  This is an advisory database check of Python runtime packages, not an audit of
  the existing Flowise/Ollama images or all host software.
- Docker image built successfully; Compose configuration validated.
- The built container passed UID 10001, read-only root, dropped capabilities,
  no-new-privileges, absent source secrets/Git history, health, authenticated
  fixture submission, duplicate suppression, and unauthenticated rejection checks.
- Original Alertmanager example validated with `amtool` v0.34.1. A temporary
  real Alertmanager delivered both firing and resolved notifications to the
  container in dry-run mode. The test resources were removed afterward.
- Existing `agent-flowise`, `agent-postgres`, and `agent-ollama` services were
  left running. Their configuration, credentials, and data were not changed.

The test client emits one Starlette warning about a future transition from
`httpx` to `httpx2`; the pinned, tested combination currently works. GitHub CI has
been added but has not run remotely before the changes are pushed.

## Remaining acceptance step and limits

**Live Flowise/Qwen3 prediction is not yet verified.** Flowise's ping endpoint
responded, but its flow listing required authentication. No flow ID, flow API key,
or tool-free flow configuration was supplied or extracted. Follow section 3 of
`docs/setup.md` to review the flow, configure it privately, and run the synthetic
fixture before opting any real alerts into the route.

The local ignored `.env` created during testing contains a newly generated
webhook token and keeps `DRY_RUN=true`; Flowise credentials remain blank. No
secrets are intended for version control, and no live gateway is left deployed
by the smoke test.

The gateway does not inspect remote Flowise nodes at runtime. Prompt wording is
not a tool permission boundary. Keep the flow tool-free and restrict edits.
Deduplication is bounded, process-local, and per group; use one worker/replica.
There is no durable incident store, result retrieval endpoint, Teams delivery,
or remediation capability in this milestone. Alertmanager ignores response
bodies; use the manual client or configured Flowise history to review advice.

## Suggested pull request text

Title: Add read-only Alertmanager webhook and Flowise analysis integration

Adds an authenticated FastAPI receiver for Alertmanager firing/resolved groups,
with safe dry-run defaults, bounded input/output and upstream calls, recent
duplicate suppression, and retryable failures. Live mode returns text analysis
from a separately reviewed tool-free Flowise/Qwen3 chatflow; it cannot execute
remediation. Adds fixtures, tests, CI, a hardened Compose service for the existing
agent-lab network, and setup/security/rollback documentation.

Validation: 56 unit tests, Ruff, runtime dependency advisory check, Docker build,
Compose validation, and real Alertmanager firing/resolved delivery in isolated
dry-run containers passed locally. Live Qwen3 acceptance remains pending private
chatflow configuration. No existing lab services were modified.
