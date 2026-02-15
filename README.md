# ClaudeStation

A Windows desktop client for Anthropic's Claude API with Projects support, prompt caching, and multi-model selection.

## Quick Start (Windows)

1. Install Python 3.11+ from https://python.org (check "Add to PATH")
2. Double-click `setup.bat` — it creates a virtual environment, installs dependencies, and launches the app
3. On first launch, go to **Settings** → **API Keys** → add your Anthropic API key

After initial setup, use `run.bat` for daily launches.

## Features

- **Projects**: Organize conversations with shared documents and custom system prompts
- **Multi-Model**: Switch between Opus 4.6/4.5, Sonnet 4.5, Haiku 4.5 per conversation
- **Prompt Caching**: System prompt + documents are cached (90% input cost savings on subsequent turns)
- **Streaming**: Real-time response display with Markdown rendering
- **Extended Thinking**: Toggle thinking mode with configurable token budget
- **Token Tracking**: Per-message and per-project cost tracking
- **Document Support**: PDF, DOCX, XLSX, TXT, Markdown, and all major code file types
- **Image Attachments**: Paste/upload images for Claude's vision capabilities
- **Secure Key Storage**: API keys stored in Windows Credential Manager via keyring
- **Proxy Support**: HTTP/HTTPS/SOCKS5 proxy configuration for network restrictions
- **Export**: Export conversations as Markdown

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Ctrl+Enter | Send message |
| Ctrl+N | New conversation |
| Ctrl+Shift+N | New project |
| Ctrl+, | Settings |
| Ctrl+L | Focus input |
| Escape | Cancel streaming |

## Data Location

All data is stored in `%USERPROFILE%\ClaudeStation\`:
- `claude_station.db` — SQLite database (conversations, messages, metadata)
- `claude_station.log` — Application log (for debugging)
- `documents/` — Uploaded project documents
- `attachments/` — Message image attachments

## Logging

Detailed logs are written to `%USERPROFILE%\ClaudeStation\claude_station.log` with timestamps, log levels, and module names. Console output shows INFO+ level; the log file captures everything (DEBUG+).

## Architecture

```
claude_station/
├── main.py                 # Entry point
├── config.py               # Constants, models, paths
├── api/
│   └── claude_client.py    # Anthropic SDK wrapper, streaming
├── core/
│   ├── project_manager.py  # Project CRUD
│   ├── conversation_manager.py  # Conversations + messages
│   ├── document_processor.py   # Text extraction (PDF/DOCX/etc)
│   ├── context_builder.py      # API request assembly + caching
│   └── token_tracker.py        # Cost calculation
├── data/
│   └── database.py         # SQLite schema + connection
├── ui/
│   ├── main_window.py      # Three-panel GUI + API worker thread
│   └── settings_dialog.py  # API key / proxy / general settings
└── utils/
    ├── key_manager.py       # Keyring-based API key storage
    └── markdown_renderer.py # MD→HTML + chat template
```
