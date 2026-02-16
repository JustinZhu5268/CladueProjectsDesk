"""Anthropic Claude API client with streaming, caching and compression."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from config import MODELS, DEFAULT_MODEL, COMPACTION_TRIGGER_TOKENS
from core.token_tracker import UsageInfo
from data.database import db

log = logging.getLogger(__name__)

# Haiku 模型用于压缩 (最低成本)
COMPRESS_MODEL = "claude-haiku-4-5-20251001"

@dataclass
class StreamEvent:
    """A streaming event from the API."""
    type: str  # "text", "thinking", "usage", "error", "done"
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
        project_id: str = "",           # 新增：用于记录日志
        conversation_id: str = "",      # 新增：用于记录日志
        use_compaction: bool = True,    # PRD v3: 是否使用 Compaction API 兜底
    ):
        """
        Send a message and yield StreamEvent objects.
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
                budget = thinking.get("budget_tokens", 1024)
                kwargs["max_tokens"] = max(max_tokens, budget + 4096)
            
            # PRD v3: 添加 Compaction API 兜底参数
            if use_compaction:
                kwargs["betas"] = ["compact-2026-01-12"]
                kwargs["context_management"] = {
                    "edits": [{
                        "type": "compact_20260112",
                        "trigger": {"type": "input_tokens", "value": COMPACTION_TRIGGER_TOKENS}
                    }]
                }
                log.debug("Compaction API enabled (trigger at %d tokens)", COMPACTION_TRIGGER_TOKENS)

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
                    
                    # 记录到api_call_log（新增）
                    if project_id and conversation_id:
                        try:
                            db.execute("""
                                INSERT INTO api_call_log 
                                (project_id, conversation_id, model_id, cache_read_tokens, cache_creation_tokens, input_tokens)
                                VALUES (?, ?, ?, ?, ?, ?)
                            """, (project_id, conversation_id, model, 
                                  usage.cache_read_tokens, usage.cache_creation_tokens, usage.input_tokens))
                            log.debug("Logged API call to cache tracker")
                        except Exception as e:
                            log.warning("Failed to log API call: %s", e)
                    
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

    def compress(
        self,
        conversation_turns: str,
        existing_summary: str,
        project_name: str = "Project",
    ) -> tuple[str, UsageInfo | None]:
        """
        使用 Haiku 模型压缩对话历史 (PRD v3)
        
        这是一个同步调用方法，用于在后台线程中执行压缩。
        
        Args:
            conversation_turns: 待压缩的对话内容
            existing_summary: 现有的摘要 (如果有)
            project_name: 项目名称
            
        Returns:
            (summary_text, usage_info)
        """
        if not self.is_configured:
            raise RuntimeError("API client not configured for compression")
        
        log.info("Starting compression with model %s", COMPRESS_MODEL)
        
        # 构建压缩提示
        system_prompt = (
            f"You are a conversation summarizer for project '{project_name}'. "
            "Output ONLY the summary in the same language as the conversation. "
            "No preamble, no explanation."
        )
        
        user_prompt = f"""请将以下对话压缩为简洁摘要。规则：
1. 保留所有关键决策和结论
2. 保留代码片段的函数签名和核心逻辑（不要只用自然语言概括代码）
3. 保留数据点、技术细节，专业术语原文
4. 保留用户偏好和约束条件
5. 删除客套、闲聊、重复内容
6. 摘要长度控制在 500 tokens 以内

现有摘要:
{existing_summary if existing_summary else '(无)'}

新对话内容:
{conversation_turns}"""
        
        try:
            import anthropic
            
            # 同步调用 (非流式)
            response = self._client.messages.create(
                model=COMPRESS_MODEL,
                max_tokens=500,
                system=[{"type": "text", "text": system_prompt}],
                messages=[{"role": "user", "content": user_prompt}],
            )
            
            # 提取响应文本
            summary = ""
            usage = None
            
            if response.content:
                for block in response.content:
                    if hasattr(block, "text"):
                        summary = block.text
                        break
            
            # 提取 usage
            if hasattr(response, "usage") and response.usage:
                u = response.usage
                usage = UsageInfo(
                    input_tokens=getattr(u, "input_tokens", 0),
                    output_tokens=getattr(u, "output_tokens", 0),
                )
                log.info(
                    "Compression complete: %d input -> %d output tokens",
                    usage.input_tokens, usage.output_tokens
                )
            
            return summary.strip(), usage
            
        except Exception as e:
            log.exception("Compression failed")
            raise