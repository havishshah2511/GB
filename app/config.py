"""Runtime configuration. Everything is env-overridable so the MVP can be
deployed without code changes."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency on python-dotenv being present)."""
    env_file = PROJECT_DIR / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv()


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    # --- server ---
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = _int("PORT", 8000)
    # Render injects RENDER_EXTERNAL_URL with the full https URL, so a deploy
    # gets correct share/status links without anyone setting anything by hand.
    PUBLIC_BASE_URL: str = (
        os.getenv("PUBLIC_BASE_URL")
        or os.getenv("RENDER_EXTERNAL_URL")
        or ""
    ).rstrip("/")

    # --- storage ---
    DB_PATH: str = os.getenv("DB_PATH", str(PROJECT_DIR / "data" / "groupbuy.db"))

    # --- admin ---
    ADMIN_USER: str = os.getenv("ADMIN_USER", "admin")
    ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "admin")
    # Signs the admin session cookie. Set this in production.
    ADMIN_SECRET: str = os.getenv("ADMIN_SECRET", "")
    ADMIN_SESSION_HOURS: int = _int("ADMIN_SESSION_HOURS", 12)

    # --- AI provider ---
    # When ANTHROPIC_API_KEY is set the LLM extractor is used and the rules
    # extractor becomes the fallback. Otherwise the app runs fully offline.
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
    LLM_MAX_TOKENS: int = _int("LLM_MAX_TOKENS", 1024)

    # --- business rules ---
    # Intent stays active until max purchase date + this grace period.
    INTENT_GRACE_DAYS: int = _int("INTENT_GRACE_DAYS", 2)
    # Send the "still interested?" nudge this many days before expiry.
    RECONFIRM_LEAD_DAYS: int = _int("RECONFIRM_LEAD_DAYS", 3)
    # Purchase windows must overlap by at least this many days to merge.
    MATCH_MIN_WINDOW_OVERLAP_DAYS: int = _int("MATCH_MIN_WINDOW_OVERLAP_DAYS", 1)
    # Minimum match score (0-100) required to join an existing group.
    MATCH_SCORE_THRESHOLD: int = _int("MATCH_SCORE_THRESHOLD", 60)

    # --- notification rules (section 20) ---
    # Progress toward the next slab, as percentages, that trigger a nudge.
    NOTIFY_PROGRESS_STEPS: tuple[int, ...] = tuple(
        int(x) for x in os.getenv("NOTIFY_PROGRESS_STEPS", "50,80,90").split(",") if x.strip()
    )
    # Also nudge when the gap to the next slab is <= this many units.
    NOTIFY_NEAR_TARGET_GAP: int = _int("NOTIFY_NEAR_TARGET_GAP", 3)
    # Max notifications per customer per group per rolling day.
    NOTIFY_MAX_PER_CUSTOMER_PER_DAY: int = _int("NOTIFY_MAX_PER_CUSTOMER_PER_DAY", 2)
    NOTIFY_DEFAULT_CHANNEL: str = os.getenv("NOTIFY_DEFAULT_CHANNEL", "whatsapp")

    # --- background worker ---
    ENABLE_BACKGROUND_WORKER: bool = _bool("ENABLE_BACKGROUND_WORKER", True)
    WORKER_INTERVAL_SECONDS: int = _int("WORKER_INTERVAL_SECONDS", 60)

    # --- misc ---
    CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "₹")
    # Which product categories the chatbot offers, in order. Everything else
    # stays in the codebase but is hidden -- flip a name back in here to
    # re-enable it, no code change needed. "*" enables every module.
    ENABLED_CATEGORIES: str = os.getenv("ENABLED_CATEGORIES", "PLY")

    # Off by default: the back office must only ever show real customer demand.
    # Set SEED_DEMO_DATA=1 on a throwaway database if you want the sample rows.
    SEED_DEMO_DATA: bool = _bool("SEED_DEMO_DATA", False)

    # Allows the back office's "Reset data" action. Leave this ON while you are
    # testing; turn it OFF (0) once real customers are in the database, so an
    # operator cannot wipe live demand by mistake.
    ALLOW_DATA_RESET: bool = _bool("ALLOW_DATA_RESET", True)

    def base_url(self, request_base: str = "") -> str:
        """Public URL used when building share links."""
        return self.PUBLIC_BASE_URL or request_base.rstrip("/") or f"http://{self.HOST}:{self.PORT}"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.ANTHROPIC_API_KEY)

    @property
    def admin_secret(self) -> str:
        # Falls back to the password so a fresh install still gets signed
        # cookies; rotating ADMIN_PASSWORD then invalidates open sessions.
        return self.ADMIN_SECRET or f"gb::{self.ADMIN_USER}::{self.ADMIN_PASSWORD}"


settings = Settings()
