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

DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Cache pricing multipliers (5min default)
CACHE_WRITE_MULTIPLIER_5M = 1.25   # 5分钟缓存写入乘数
CACHE_WRITE_MULTIPLIER_1H = 2.0    # 1小时缓存写入乘数
CACHE_READ_MULTIPLIER = 0.10       # 缓存读取乘数

# ── Context Management ─────────────────────────────────
MAX_HISTORY_TURNS = 40          # max message pairs before compression
RESPONSE_TOKEN_RESERVE = 8192  # tokens reserved for model response
CONTEXT_USAGE_THRESHOLD = 0.80 # trigger compression at 80% of context window

# ── Compression Settings (PRD v3) ───────────────────────
COMPRESS_AFTER_TURNS = 10       # 触发压缩的轮次 (默认 N=10)
COMPRESS_BATCH_SIZE = 5         # 每次压缩的轮数 (默认 K=5)
MAX_SUMMARY_TOKENS = 500        # 单次摘要最大 token 数
SUMMARY_RECOMPRESS_THRESHOLD = 3000  # 摘要超过此阈值时重新压缩
RECENT_TURNS_KEPT = 10          # 保留最近 N 轮完整对话

# Cache TTL 选项
CACHE_TTL_DEFAULT = "5m"       # 默认 5 分钟
CACHE_TTL_1H = "1h"            # 1 小时选项

# Compaction API
COMPACTION_TRIGGER_TOKENS = 160000  # 触发服务端压缩的阈值 (200K * 80%)

# ── UI Constants ───────────────────────────────────────
SIDEBAR_WIDTH = 260
RIGHT_PANEL_WIDTH = 300
MIN_WINDOW_WIDTH = 1100
MIN_WINDOW_HEIGHT = 700

# ── Keyring ────────────────────────────────────────────
KEYRING_SERVICE = "ClaudeStation"
