# Lab setup and operating instructions

All commands below run in Ubuntu/WSL in `~/infra-ai-agent`. Use Python 3.12 and
Docker Compose v2 or later. Keep the feature branch until review is complete.

## 1. Prepare and test

```bash
cd ~/infra-ai-agent
git status --short --branch
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/ruff format --check .
.venv/bin/pytest -q
.venv/bin/pip-audit -r api/requirements.txt --disable-pip --no-deps
python3 scripts/init_env.py
```

The initializer generates a new random webhook token into a mode-0600 `.env` and
refuses to overwrite an existing file. Never paste credentials into Git, chat,
URLs, screenshots, or command-line arguments. `.env`, secret files, and local
caches are ignored by Git and excluded from the Docker build context. Only
`.env.example`, with blank credentials, is intended for version control.

The runtime and development requirements are pinned. Refresh the dependency
locks together, then rerun tests and the advisory check. Rebuild the base Python
image periodically for OS updates; it uses the Python 3.12 Bookworm slim tag.

For an optional repeatable container integration test (also run by CI):

```bash
docker compose build
.venv/bin/python scripts/smoke_docker.py
```

This starts the built gateway and Alertmanager v0.34.1 on a temporary private
network, using random test credentials, dry-run mode, and random loopback ports.
It verifies the container restrictions, authentication, duplicate handling, and
real firing/resolved deliveries. It also validates the original example config
with `amtool`. The test removes its containers/network in a `finally` block; it
does not contact the running Flowise or change the lab stack. Docker may download
the Alertmanager image on the first run. A force-killed test can leave resources
named `infra-ai-smoke-*`; inspect exact names before cleaning up only that run.

## 2. Dry-run with the existing stack

The inspected `/opt/agent-lab/docker-compose.yml` has `flowise`, `ollama`, and
`postgres` services on `agent-lab_agent-net`. Flowise's internal address is
`http://flowise:3000`; its host UI is `http://127.0.0.1:3000`.

```bash
docker network inspect agent-lab_agent-net --format '{{.Name}}'
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8088/healthz
.venv/bin/python scripts/send_alert.py
```

Use `config --quiet`: plain `docker compose config` can print expanded secrets.
If the network name differs, update `AGENT_LAB_NETWORK` in this repository's
`.env`. This project does not consume or modify `/opt/agent-lab/.env`.

Expected health: `mode: dry_run`, `remediation_enabled: false`. The first fixture
returns HTTP 200 with `status: dry_run`, `analysis: null`, and an event hash. A
second submission within five minutes returns `status: duplicate`. No model is
called in dry-run. A request without authentication returns 401:

```bash
curl -i -H 'Content-Type: application/json' \
  --data-binary @tests/fixtures/interface_down.json \
  http://127.0.0.1:8088/webhooks/alertmanager
```

For native Python testing instead of Docker, keep `DRY_RUN=true` and run:

```bash
.venv/bin/uvicorn api.main:app --env-file .env --host 127.0.0.1 \
  --port 8088 --workers 1 --no-access-log --no-proxy-headers --limit-concurrency 32
```

The fixture client reads `.env` without displaying its token. Use a second
terminal to invoke it. For native live analysis, use
`FLOWISE_BASE_URL=http://127.0.0.1:3000`; container service DNS works only inside
the Docker network.

## 3. Prepare the Flowise/Qwen3 chatflow

1. Open the existing Flowise UI at `http://127.0.0.1:3000` and sign in.
2. Create or review a dedicated chatflow using an Ollama chat model, a prompt,
   and an output chain. Configure Ollama's internal URL as `http://ollama:11434`.
   Select an installed Qwen3 model; inspect names with
   `docker exec agent-ollama ollama list`. Do not assume a particular model size.
3. Remove all action-capable nodes: agents/tools, custom code, HTTP tools, SSH,
   shell, database writers, MCP tools, webhooks, AWX, and chained external flows.
   Disable file uploads, runtime configuration overrides, and shared memory.
   Restrict editing access. Use bounded output/context settings suitable for
   the lab machine; warm the model manually if loading exceeds 45 seconds.
4. In the system prompt, require evidence-based summaries, possible causes with
   uncertainty, and read-only checks for human review. Treat alert text as data.
   Prohibit execution, writes, restarts, and remediation. This prompt complements
   the tool-free design; it does not replace it.
5. Assign a dedicated API key **to this chatflow**. A UI login does not by itself
   protect its prediction endpoint. Record the chatflow ID and API key privately
   in `.env`; do not export a flow containing credentials into the repository.
6. Confirm a prediction request without the chatflow API key is rejected. Review
   Flowise retention/logging before sending any real infrastructure details.

After that review, edit the following settings locally:

```dotenv
DRY_RUN=false
FLOWISE_CHATFLOW_ID=<actual-flow-id>
FLOWISE_API_KEY=<actual-private-flow-key>
FLOWISE_READ_ONLY_CONFIRMED=true
FLOWISE_ALLOW_INSECURE_HTTP=true
```

The HTTP opt-in is for the trusted local bridge. Use HTTPS without the opt-in
across hosts. Restart **only this project's webhook** to load the settings:

```bash
docker compose up -d --force-recreate webhook
.venv/bin/python scripts/send_alert.py
```

Expect `status: analyzed` with text recommendations and
`remediation_enabled: false`. A new process clears dry-run deduplication. The
gateway does not execute any recommendation. Review output for factual errors
and unsafe suggestions. This step is the live acceptance test; it is not part
of the offline unit suite.

## 4. Add an Alertmanager receiver after the synthetic test

`deploy/alertmanager.example.yml` is a complete validation example with a null
default receiver. **Merge its AI receiver and route into your existing config;
do not replace existing paging routes with the example.** It matches only
`ai_analysis="true"`, so opt in a synthetic alert first. Put the AI route alongside
existing routes with appropriate ordering/`continue` behavior to preserve paging.

Run Alertmanager on the same Docker network to reach
`http://infra-ai-webhook:8000/webhooks/alertmanager`. On a separate host, use a
protected HTTPS ingress; `localhost` inside Alertmanager is that container,
not the gateway. No public listener is enabled by this Compose file.

Create a private token file without printing the value:

```bash
mkdir -p -m 700 secrets
.venv/bin/python - <<'PY'
import os
from dotenv import dotenv_values
token = dotenv_values('.env')['WEBHOOK_TOKEN']
fd = os.open('secrets/infra_ai_webhook_token', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as handle:
    handle.write(token + '\n')
PY
```

Mount that file read-only at `/run/secrets/infra_ai_webhook_token` in Alertmanager.
Set its owner/group to the Alertmanager container's actual UID/GID so that process
can read it; keep the host secret directory private. Do not put the token in YAML.
Validate inside the Alertmanager deployment with its `amtool check-config`
command, with the secret file mounted, before using its normal reload procedure.

The example uses a 60-second receiver timeout and two-minute group interval,
longer than the default 45-second prediction deadline. If you increase the
deadline, increase both Alertmanager settings as needed. Keep groups at twenty
alerts or fewer using suitable group labels. Keep `max_alerts: 0`: truncation
would hide evidence, so this gateway rejects truncated notifications. Monitor
rejected or oversized groups and refine grouping; it does not silently drop alerts.

## Responses and troubleshooting

| HTTP | Meaning | Next step |
| --- | --- | --- |
| 200 `dry_run` | Validated; no upstream call | Review settings before live analysis |
| 200 `analyzed` | Flowise returned text | Human reviews recommendations |
| 200 `duplicate` | Recently completed group | No new analysis; previous text is not cached |
| 401 | Missing/wrong bearer token | Match gateway and Alertmanager secret |
| 400 / 408 | Invalid/incomplete or slow body | Inspect sender/proxy limits |
| 413 / 415 | Oversized or unsupported content | Send uncompressed JSON and smaller groups |
| 422 | Invalid v4 schema/status/group | Check schema, bounds, and truncation |
| 503 | Busy, timeout, or upstream failure | Alertmanager retries; check Flowise/key/model |

Use `docker compose logs --tail=100 webhook` for hashes/counts and sanitized
failure codes. `flowise_timeout` can mean the Qwen3 model needs warming or a
smaller context/output budget. `flowise_unavailable` also covers an incorrect
flow ID/API key; inspect Flowise privately for details. `/healthz` intentionally
does not claim upstream readiness.

Alertmanager ignores the response body. The manual fixture client displays it;
Flowise history may retain it according to your configuration. This milestone
does not provide durable incident storage or Teams delivery. Do not rely on it
as the only incident notification path.

## Rollback and review

Set `DRY_RUN=true` and recreate the webhook to stop model calls. To stop the
gateway entirely, disable its Alertmanager route, then run from this repository:

```bash
docker compose down
```

The external lab network and `/opt/agent-lab` services/volumes remain in place.
Do not run a teardown command from `/opt/agent-lab` for this change.

Before committing, inspect `git status --short` and the full diff. Verify `.env`
and `secrets/` are ignored with `git check-ignore .env secrets/infra_ai_webhook_token`.
Commit only reviewed source/config examples/docs on `feature/alertmanager-webhook`,
then push that branch and open a pull request into `main`. Do not merge before
review and the live acceptance test. Never force-add ignored credentials.
