"""Anthropic Claude API client with streaming and caching."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import MODELS, DEFAULT_MODEL
from core.token_tracker import UsageInfo

log = logging.getLogger(__name__)


@dataclass
class StreamEvent:
    """A streaming event from the API."""
    type: str                 # "text", "thinking", "usage", "error", "done"
    text: str = ""
    usage: UsageInfo | None = None
    error: str = ""
    stop_reason: str = ""


class ClaudeClient:
    """Wrapper around the Anthropic Python SDK."""

    def __init__(self) -> None:
        self._client = None
        self._api_key: str = ""
        self._proxy: str = ""

    def configure(self, api_key: str, proxy: str = "") -> None:
        """Set API key and optional proxy, (re)create client."""
        import anthropic
        import httpx

        self._api_key = api_key
        self._proxy = proxy

        kwargs: dict[str, Any] = {"api_key": api_key}
        if proxy:
            kwargs["http_client"] = httpx.Client(proxy=proxy)
            log.info("API client configured with proxy: %s", proxy.split("@")[-1])

        self._client = anthropic.Anthropic(**kwargs)
        log.info("Anthropic client initialized (key: ...%s)", api_key[-6:])

    @property
    def is_configured(self) -> bool:
        return self._client is not None and bool(self._api_key)

    def stream_message(
        self,
        messages: list[dict],
        system_content: list[dict],
        model: str = DEFAULT_MODEL,
        max_tokens: int = 8192,
        thinking: dict | None = None,
    ):
        """
        Send a message and yield StreamEvent objects.
        
        Args:
            messages: Conversation history in Messages API format.
            system_content: System prompt as list of content blocks (with cache_control).
            model: Model ID string.
            max_tokens: Maximum output tokens.
            thinking: Optional thinking config {"type": "enabled", "budget_tokens": N}.
        
        Yields:
            StreamEvent objects for text deltas, thinking, usage, and completion.
        """
        if not self.is_configured:
            yield StreamEvent(type="error", error="API client not configured. Set your API key in Settings.")
            return

        model_info = MODELS.get(model)
        if not model_info:
            log.warning("Unknown model '%s', falling back to %s", model, DEFAULT_MODEL)
            model = DEFAULT_MODEL

        log.info("API call: model=%s, messages=%d, max_tokens=%d, thinking=%s",
                 model, len(messages), max_tokens, bool(thinking))
        log.debug("System content blocks: %d, total chars: %d",
                  len(system_content),
                  sum(len(b.get("text", "")) for b in system_content))

        try:
            import anthropic

            kwargs: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "system": system_content,
                "messages": messages,
            }
            if thinking:
                kwargs["thinking"] = thinking
                # Extended thinking requires higher max_tokens
                budget = thinking.get("budget_tokens", 1024)
                kwargs["max_tokens"] = max(max_tokens, budget + 4096)

            full_text = ""
            full_thinking = ""
            usage = UsageInfo()

            with self._client.messages.stream(**kwargs) as stream:
                for event in stream:
                    etype = getattr(event, "type", "")

                    if etype == "content_block_start":
                        block = getattr(event, "content_block", None)
                        if block and getattr(block, "type", "") == "thinking":
                            log.debug("Thinking block started")

                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta:
                            delta_type = getattr(delta, "type", "")
                            if delta_type == "text_delta":
                                txt = getattr(delta, "text", "")
                                full_text += txt
                                yield StreamEvent(type="text", text=txt)
                            elif delta_type == "thinking_delta":
                                txt = getattr(delta, "thinking", "")
                                full_thinking += txt
                                yield StreamEvent(type="thinking", text=txt)

                # Get final message for usage
                final = stream.get_final_message()
                if final and hasattr(final, "usage"):
                    u = final.usage
                    usage = UsageInfo(
                        input_tokens=getattr(u, "input_tokens", 0),
                        output_tokens=getattr(u, "output_tokens", 0),
                        cache_creation_tokens=getattr(u, "cache_creation_input_tokens", 0),
                        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0),
                    )
                    log.info(
                        "API response: %d input, %d output, %d cache_write, %d cache_read, stop=%s",
                        usage.input_tokens, usage.output_tokens,
                        usage.cache_creation_tokens, usage.cache_read_tokens,
                        getattr(final, "stop_reason", "?"),
                    )

            yield StreamEvent(
                type="done",
                text=full_text,
                usage=usage,
                stop_reason=getattr(final, "stop_reason", "") if final else "",
            )

        except anthropic.AuthenticationError as e:
            log.error("Authentication failed: %s", e)
            yield StreamEvent(type="error", error="Invalid API key. Please check your key in Settings.")

        except anthropic.RateLimitError as e:
            log.warning("Rate limited: %s", e)
            yield StreamEvent(type="error", error="Rate limited by Anthropic. Please wait a moment and try again.")

        except anthropic.APIStatusError as e:
            log.error("API error %d: %s", e.status_code, e.message)
            yield StreamEvent(type="error", error=f"API error ({e.status_code}): {e.message}")

        except anthropic.APIConnectionError as e:
            log.error("Connection error: %s", e)
            yield StreamEvent(type="error",
                              error="Cannot connect to Anthropic API. Check your network/proxy settings.")

        except Exception as e:
            log.exception("Unexpected error during API call")
            yield StreamEvent(type="error", error=f"Unexpected error: {str(e)}")

    def test_connection(self) -> tuple[bool, str]:
        """Test API connectivity. Returns (success, message)."""
        if not self.is_configured:
            return False, "API key not configured"
        try:
            import anthropic
            # Minimal API call to test
            response = self._client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            return True, f"Connected! Model: {response.model}"
        except anthropic.AuthenticationError:
            return False, "Invalid API key"
        except anthropic.APIConnectionError as e:
            return False, f"Connection failed: {e}"
        except Exception as e:
            return False, f"Error: {e}"
