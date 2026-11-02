import json
from contextlib import ExitStack
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from api.config import Settings
from api.main import create_app

TOKEN = "unit-test-token-" + "a" * 40
FLOWISE_KEY = "unit-test-flowise-key"
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.fixture
def payload():
    return json.loads((Path(__file__).parent / "fixtures/interface_down.json").read_text())


@pytest.fixture
def client_factory():
    with ExitStack() as stack:

        def make(handler=None, live=False, **overrides):
            def forbidden(request):
                raise AssertionError("Dry-run must not contact Flowise")

            config = Settings(
                webhook_token=TOKEN,
                dry_run=not live,
                flowise_chatflow_id="test-flow",
                flowise_api_key=FLOWISE_KEY,
                flowise_read_only_confirmed=True,
                flowise_allow_insecure_http=True,
                **overrides,
            )
            app = create_app(config, httpx.MockTransport(handler or forbidden))
            return stack.enter_context(TestClient(app))

        yield make
