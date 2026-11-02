"""Create a private local .env once without printing the generated token."""

import os
import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = (root / ".env.example").read_text()
content = template.replace(
    "WEBHOOK_TOKEN=\n", "WEBHOOK_TOKEN=" + secrets.token_urlsafe(48) + "\n", 1
)
try:
    fd = os.open(root / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit(".env already exists; no changes made") from None
with os.fdopen(fd, "w") as handle:
    handle.write(content)
print("Created private .env with a new webhook token; dry-run is enabled.")
