"""Global configuration and constants for ClaudeStation."""
from __future__ import annotations

import os
import sys
import logging
from pathlib import Path
from dataclasses import dataclass, field

# ── Paths ──────────────────────────────────────────────
APP_NAME = "ClaudeStation"
APP_VERSION = "1.0.0"

if sys.platform == "win32":
    DATA_DIR = Path(os.environ.get("USERPROFILE", "~")) / APP_NAME
else:
    DATA_DIR = Path.home() / APP_NAME

DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "claude_station.db"
LOG_PATH = DATA_DIR / "claude_station.log"
DOCS_DIR = DATA_DIR / "documents"
DOCS_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENTS_DIR = DATA_DIR / "attachments"
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Logging ────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)-25s | %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure application-wide logging to both file and console."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File handler - DEBUG level (everything)
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    # Console handler - INFO level
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))

    root.addHandler(fh)
    root.addHandler(ch)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


# ── Model Definitions ─────────────────────────────────
@dataclass
class ModelInfo:
    """Definition of a Claude model with pricing."""
    model_id: str
    display_name: str
    input_price: float    # $ per 1M tokens
    output_price: float   # $ per 1M tokens
    context_window: int   # tokens
    supports_thinking: bool = True
    supports_cache_1h: bool = True


MODELS: dict[str, ModelInfo] = {
    "claude-opus-4-6": ModelInfo(
        model_id="claude-opus-4-6",
        display_name="Claude Opus 4.6 (Latest)",
        input_price=5.00, output_price=25.00,
        context_window=200_000,
    ),
    "claude-opus-4-5-20251101": ModelInfo(
        model_id="claude-opus-4-5-20251101",
        display_name="Claude Opus 4.5",
        input_price=5.00, output_price=25.00,
        context_window=200_000,
    ),
    "claude-sonnet-4-5-20250929": ModelInfo(
        model_id="claude-sonnet-4-5-20250929",
        display_name="Claude Sonnet 4.5",
        input_price=3.00, output_price=15.00,
        context_window=200_000,
    ),
    "claude-haiku-4-5-20251001": ModelInfo(
        model_id="claude-haiku-4-5-20251001",
        display_name="Claude Haiku 4.5",
        input_price=1.00, output_price=5.00,
        context_window=200_000,
    ),
}

DEFAULT_MODEL = "claude-sonnet-4-5-20250929"

# Cache pricing multipliers
CACHE_WRITE_MULTIPLIER = 1.25   # 1.25x base input price
CACHE_READ_MULTIPLIER = 0.10    # 0.1x base input price

# ── Context Management ─────────────────────────────────
MAX_HISTORY_TURNS = 40          # max message pairs before compression
RESPONSE_TOKEN_RESERVE = 8192  # tokens reserved for model response
CONTEXT_USAGE_THRESHOLD = 0.80 # trigger compression at 80% of context window

# ── UI Constants ───────────────────────────────────────
SIDEBAR_WIDTH = 260
RIGHT_PANEL_WIDTH = 300
MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700

# ── Keyring ────────────────────────────────────────────
KEYRING_SERVICE = "ClaudeStation"
