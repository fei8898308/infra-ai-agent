"""Send a synthetic fixture without putting credentials in shell arguments."""

import argparse
import os
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
load_dotenv(root / ".env")
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8088/webhooks/alertmanager")
parser.add_argument("--fixture", type=Path, default=root / "tests/fixtures/interface_down.json")
args = parser.parse_args()
token = os.environ.get("WEBHOOK_TOKEN", "")
if not token and os.environ.get("WEBHOOK_TOKEN_FILE"):
    token = Path(os.environ["WEBHOOK_TOKEN_FILE"]).read_text().strip()
if not token:
    raise SystemExit("Set WEBHOOK_TOKEN or WEBHOOK_TOKEN_FILE in your environment or .env")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


request = urllib.request.Request(
    args.url,
    data=args.fixture.read_bytes(),
    headers={
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    },
)
opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
try:
    with opener.open(request, timeout=130) as response:
        print(response.read().decode())
except urllib.error.HTTPError as exc:
    print(exc.read().decode())
    raise SystemExit(f"Webhook returned HTTP {exc.code}") from None
