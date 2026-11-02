"""Exercise the built image and real Alertmanager on a temporary private network.

Requires Docker Compose, the built infra-ai-agent:alertmanager-webhook image, and
a local .env (scripts/init_env.py). Uses only generated test secrets and dry-run.
Creates and removes its own containers/network; never touches agent-lab services.
"""

import copy
import json
import os
import secrets
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
ALERTMANAGER_IMAGE = "prom/alertmanager:v0.34.1"


def run(*args, **kwargs):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=False, **kwargs)
    if result.returncode:
        # Commands contain file paths, never token values.
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def request(url, data=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(
        url, data=json.dumps(data).encode() if data is not None else None, headers=headers
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        body = response.read()
        return json.loads(body) if body else None


def wait_for(check, description, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if check():
                return
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.5)
    raise RuntimeError("Timed out waiting for " + description)


def main():
    project = "infra-ai-smoke-" + uuid4().hex[:10]
    network = project + "-net"
    alertmanager = project + "-alertmanager"
    token = secrets.token_urlsafe(48)
    env = {**os.environ, "AGENT_LAB_NETWORK": network, "WEBHOOK_PORT": "0"}
    network_created = False
    with tempfile.TemporaryDirectory(prefix=project) as temporary:
        directory = Path(temporary)
        env_file = directory / "smoke.env"
        env_file.write_text(
            (ROOT / ".env.example")
            .read_text()
            .replace("WEBHOOK_TOKEN=\n", "WEBHOOK_TOKEN=" + token + "\n", 1)
        )
        env_file.chmod(0o600)
        override = directory / "override.json"
        override.write_text(json.dumps({"services": {"webhook": {"env_file": [str(env_file)]}}}))
        compose = [
            "docker",
            "compose",
            "-p",
            project,
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(override),
        ]
        secret_file = directory / "token"
        secret_file.write_text(token + "\n")
        # The directory remains 0700. This disposable file must be readable by
        # the non-root Alertmanager UID through its individual read-only mount.
        secret_file.chmod(0o444)
        original_config = directory / "original.yml"
        original_config.write_text((ROOT / "deploy/alertmanager.example.yml").read_text())
        config = directory / "alertmanager.yml"
        config.write_text(
            original_config.read_text()
            .replace("group_wait: 10s", "group_wait: 1s")
            .replace("group_interval: 2m", "group_interval: 3s")
            .replace("timeout: 60s", "timeout: 2s")
        )
        secret_mount = f"{secret_file}:/run/secrets/infra_ai_webhook_token:ro"
        try:
            run("docker", "network", "create", network)
            network_created = True
            run(*compose, "up", "-d", "--no-build", env=env)
            container = run(*compose, "ps", "-q", "webhook", env=env)
            binding = run(*compose, "port", "webhook", "8000", env=env)
            api = "http://" + binding
            wait_for(lambda: request(api + "/healthz")["mode"] == "dry_run", "gateway")
            inspection = json.loads(run("docker", "inspect", container))[0]
            assert inspection["Config"]["User"] == "10001:10001"
            assert inspection["HostConfig"]["ReadonlyRootfs"] is True
            assert inspection["HostConfig"]["CapDrop"] == ["ALL"]
            assert not inspection["Mounts"]
            assert "no-new-privileges:true" in inspection["HostConfig"]["SecurityOpt"]
            assert run("docker", "exec", container, "id", "-u") == "10001"
            run(
                "docker",
                "exec",
                container,
                "python",
                "-c",
                "from pathlib import Path; assert not Path('/app/.env').exists(); "
                "assert not Path('/app/.git').exists()",
            )
            fixture = json.loads((ROOT / "tests/fixtures/interface_down.json").read_text())
            assert request(api + "/webhooks/alertmanager", fixture, token)["status"] == "dry_run"
            assert request(api + "/webhooks/alertmanager", fixture, token)["status"] == "duplicate"
            try:
                request(api + "/webhooks/alertmanager", fixture)
                raise AssertionError("Missing bearer was accepted")
            except urllib.error.HTTPError as exc:
                assert exc.code == 401
            print(
                "PASS: hardened container, health, authentication, fixture, duplicate", flush=True
            )

            run(
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "/bin/amtool",
                "-v",
                f"{original_config}:/etc/alertmanager/alertmanager.yml:ro",
                "-v",
                secret_mount,
                ALERTMANAGER_IMAGE,
                "check-config",
                "/etc/alertmanager/alertmanager.yml",
            )
            print("PASS: original Alertmanager configuration validates", flush=True)
            run(
                "docker",
                "run",
                "-d",
                "--name",
                alertmanager,
                "--network",
                network,
                "-p",
                "127.0.0.1::9093",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--tmpfs",
                "/alertmanager:rw,size=16m,mode=1777",
                "-v",
                f"{config}:/etc/alertmanager/alertmanager.yml:ro",
                "-v",
                secret_mount,
                ALERTMANAGER_IMAGE,
                "--config.file=/etc/alertmanager/alertmanager.yml",
                "--storage.path=/alertmanager",
                "--cluster.listen-address=",
                "--log.level=warn",
            )
            am_url = "http://" + run("docker", "port", alertmanager, "9093/tcp")
            wait_for(lambda: request(am_url + "/api/v2/status") is not None, "Alertmanager")
            alert = copy.deepcopy(fixture["alerts"][0])
            now = datetime.now(UTC)
            alert["labels"]["ai_analysis"] = "true"
            alert["startsAt"] = (now - timedelta(seconds=30)).isoformat()
            alert["endsAt"] = (now + timedelta(minutes=5)).isoformat()
            del alert["status"], alert["fingerprint"]
            request(am_url + "/api/v2/alerts", [alert])

            def delivered(state, minimum):
                logs = subprocess.run(
                    ["docker", "logs", container], capture_output=True, text=True, check=True
                )
                text = logs.stdout + logs.stderr
                assert token not in text
                return text.count("alert_status=" + state) >= minimum

            wait_for(lambda: delivered("firing", 2), "real firing webhook")
            alert["endsAt"] = datetime.now(UTC).isoformat()
            request(am_url + "/api/v2/alerts", [alert])
            wait_for(lambda: delivered("resolved", 1), "real resolved webhook")
            print(
                "PASS: real Alertmanager firing and resolved deliveries; no token in logs",
                flush=True,
            )
        except Exception:
            diagnostics = subprocess.run(
                ["docker", "logs", alertmanager], capture_output=True, text=True, check=False
            )
            print(
                (diagnostics.stdout + diagnostics.stderr).replace(token, "<redacted>"), flush=True
            )
            raise
        finally:
            subprocess.run(["docker", "rm", "-f", alertmanager], capture_output=True, check=False)
            subprocess.run([*compose, "down"], env=env, cwd=ROOT, capture_output=True, check=False)
            if network_created:
                run("docker", "network", "rm", network)
            print("Temporary smoke-test containers and network removed.", flush=True)


if __name__ == "__main__":
    main()
