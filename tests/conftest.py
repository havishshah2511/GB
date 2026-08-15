"""Test fixtures. Every test runs against a throwaway SQLite file with the
background worker and demo seed disabled."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_TMP = Path(tempfile.mkdtemp(prefix="groupbuy-tests-"))
os.environ["DB_PATH"] = str(_TMP / "test.db")
os.environ["SEED_DEMO_DATA"] = "0"
os.environ["ENABLE_BACKGROUND_WORKER"] = "0"
os.environ["ANTHROPIC_API_KEY"] = ""          # force the offline rules engine
os.environ["PUBLIC_BASE_URL"] = "http://testserver"
os.environ.setdefault("ADMIN_USER", "admin")
os.environ.setdefault("ADMIN_PASSWORD", "admin")


@pytest.fixture(autouse=True)
def clean_db():
    """Fresh schema for every test — matching and pricing are stateful."""
    from app.db import reset_db
    from app.services import pricing

    reset_db()
    pricing.seed_product_slabs()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        c.auth = ("admin", "admin")
        yield c


@pytest.fixture
def chat():
    """Drive the chatbot the way the browser does."""
    from app.services import conversation

    def _drive(session_id: str, message: str = "", **kwargs):
        return conversation.handle(session_id, message, base_url="http://testserver", **kwargs)

    return _drive


def answer_all(chat, session_id, opening_message, answers, limit=15):
    """Play a whole conversation, answering with `answers[slot]` or the first chip."""
    chat(session_id, "")
    reply = chat(session_id, opening_message)
    for _ in range(limit):
        if reply.get("done"):
            break
        question = reply.get("question")
        if not question:
            break
        slot = question["slot"]
        value = answers.get(slot)
        if value is None:
            value = question["chips"][0]["value"] if question["chips"] else "skip"
        reply = chat(session_id, value)
    return reply
