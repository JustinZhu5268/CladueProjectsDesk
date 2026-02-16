"""
Context Builder with Four-Layer Architecture (PRD v3)

四层上下文架构：
- Layer 1: System Prompt + Project Documents (缓存断点 1)
- Layer 2: Rolling Summary (缓存断点 2 - 仅当摘要超过 1024 tokens)
- Layer 3: Recent Messages (未缓存)
- Layer 4: Current User Message

核心创新：将对话摘要作为第二个 cache breakpoint，享受 0.1x 缓存读取价格
"""
from __future__ import annotations

import logging
import json

from config import (
    MODELS, 
    RESPONSE_TOKEN_RESERVE, 
    MAX_HISTORY_TURNS, 
    CONTEXT_USAGE_THRESHOLD,
    RECENT_TURNS_KEPT,
    CACHE_TTL_DEFAULT,
    CACHE_WRITE_MULTIPLIER_5M,
    CACHE_WRITE_MULTIPLIER_1H,
    COMPACTION_TRIGGER_TOKENS,
)
from core.document_processor import DocumentProcessor
from core.conversation_manager import ConversationManager, Message
from core.token_tracker import TokenTracker
from data.database import db

log = logging.getLogger(__name__)

# 1024 token 缓存门槛 (PRD v3)
CACHE_BREAKPOINT_THRESHOLD = 1024


class ContextBuilder:
    """
    四层上下文构建器
    
    核心设计：
    1. Layer 1 (System + Docs): 缓存断点，几乎不变
    2. Layer 2 (Rolling Summary): 缓存断点，每 10 轮更新一次
    3. Layer 3 (Recent Messages): 未缓存，只保留最近 N 轮
    4. Layer 4 (Current Message): 未缓存
    """

    def __init__(self, cache_ttl: str = CACHE_TTL_DEFAULT):
        self.doc_processor = DocumentProcessor()
        self.conv_manager = ConversationManager()
        self.tracker = TokenTracker(cache_ttl=cache_ttl)
        self._cache_ttl = cache_ttl

    @property
    def cache_ttl(self) -> str:
        return self._cache_ttl

    @cache_ttl.setter
    def cache_ttl(self, value: str) -> None:
        """设置缓存 TTL"""
        self._cache_ttl = value
        self.tracker.cache_ttl = value

    def build(
        self,
        project_id: str,
        conversation_id: str,
        user_message: str,
        system_prompt: str,
        model_id: str,
        user_attachments: list[dict] | None = None,
    ) -> tuple[list[dict], list[dict], int]:
        """
        构建完整的 API 请求载荷
        
        Returns:
            (system_content, messages, estimated_tokens)
        """
        model = MODELS.get(model_id, MODELS["claude-sonnet-4-5-20250929"])
        context_limit = model.context_window
        budget = int(context_limit * CONTEXT_USAGE_THRESHOLD) - RESPONSE_TOKEN_RESERVE

        # ── Layer 1: System Prompt + Documents (缓存) ──
        doc_context = self.doc_processor.get_project_context(project_id)
        system_text = self._build_system_text(system_prompt, doc_context)
        system_tokens = self.tracker.estimate_tokens(system_text)

        cache_config = {"type": "ephemeral"}
        if self._cache_ttl == "1h":
            cache_config["ttl"] = "1h"

        system_content = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": cache_config,
            }
        ]

        # ── Layer 2: Rolling Summary (条件性缓存) ──
        conv = self.conv_manager.get_conversation(conversation_id)
        summary_block = None
        summary_tokens = 0
        
        if conv and conv.rolling_summary:
            summary_text = f"<conversation_summary>\n{conv.rolling_summary}\n</conversation_summary>"
            summary_tokens = self.tracker.estimate_tokens(summary_text)
            
            summary_block = {
                "type": "text",
                "text": summary_text,
            }
            
            # PRD v3: 仅当摘要超过 1024 tokens 时才标记为缓存断点
            if summary_tokens >= CACHE_BREAKPOINT_THRESHOLD:
                summary_block["cache_control"] = cache_config
                log.debug("Summary %d tokens - using cache breakpoint", summary_tokens)
            else:
                log.debug("Summary %d tokens - below threshold, not cached", summary_tokens)
            
            system_content.append(summary_block)

        # ── Layer 3: Recent Messages (未缓存) ──
        remaining_budget = budget - system_tokens - summary_tokens
        if remaining_budget < 1000:
            log.warning("Very little room for conversation (%d tokens left)", remaining_budget)
            remaining_budget = max(remaining_budget, 1000)

        # 获取消息：优先使用摘要，然后取最近的 N 轮
        all_messages = self.conv_manager.get_messages(conversation_id)
        
        # 过滤已压缩的消息
        if conv and conv.last_compressed_msg_id:
            for i, msg in enumerate(all_messages):
                if msg.id == conv.last_compressed_msg_id:
                    all_messages = all_messages[i+1:]
                    break

        # 保留最近 N 轮完整对话
        recent_messages = self._get_recent_messages(all_messages, RECENT_TURNS_KEPT)
        
        # 限制在 token 预算内
        history = self._fit_history(recent_messages, remaining_budget)

        # 构建消息列表
        messages = []
        for msg in history:
            messages.append({"role": msg.role, "content": msg.content})

        # ── Layer 4: Current User Message ──
        if user_attachments:
            user_content: list[dict] = [{"type": "text", "text": user_message}]
            for att in user_attachments:
                if att.get("type") == "image":
                    user_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": att.get("media_type", "image/png"),
                            "data": att["data"],
                        }
                    })
                elif att.get("type") == "document":
                    user_content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": att.get("media_type", "application/pdf"),
                            "data": att["data"],
                        }
                    })
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": user_message})

        # 预估总 token 数
        msg_tokens = self._estimate_message_tokens(messages)
        total_estimated = system_tokens + summary_tokens + msg_tokens

        # 计算缓存相关统计
        cached_tokens = system_tokens
        if summary_tokens >= CACHE_BREAKPOINT_THRESHOLD:
            cached_tokens += summary_tokens

        log.info(
            "Context built [4-layer]: L1=%d, L2=%d(cached=%s), L3=%d, total=%d/%d tokens",
            system_tokens, 
            summary_tokens,
            "yes" if summary_tokens >= CACHE_BREAKPOINT_THRESHOLD else "no",
            msg_tokens,
            total_estimated, 
            context_limit,
        )

        return system_content, messages, total_estimated

    def estimate_request(
        self, project_id: str, conversation_id: str,
        user_message: str, system_prompt: str, model_id: str,
    ) -> dict:
        """
        预估 token 和成本 (PRD v3 修正版)
        
        复用 build() 逻辑来准确预估，而非简单估算全量历史
        """
        # 获取系统内容 token
        doc_context = self.doc_processor.get_project_context(project_id)
        system_text = self._build_system_text(system_prompt, doc_context)
        system_tokens = self.tracker.estimate_tokens(system_text)

        # 获取摘要 token
        conv = self.conv_manager.get_conversation(conversation_id)
        summary_tokens = 0
        if conv and conv.rolling_summary:
            summary_tokens = self.tracker.estimate_tokens(conv.rolling_summary)

        # 获取消息 token (使用摘要后剩余的)
        all_messages = self.conv_manager.get_messages(conversation_id)
        
        if conv and conv.last_compressed_msg_id:
            for i, msg in enumerate(all_messages):
                if msg.id == conv.last_compressed_msg_id:
                    all_messages = all_messages[i+1:]
                    break

        recent_messages = self._get_recent_messages(all_messages, RECENT_TURNS_KEPT)
        history_tokens = sum(
            self.tracker.estimate_tokens(m.content) for m in recent_messages
        )

        user_tokens = self.tracker.estimate_tokens(user_message)

        total = system_tokens + summary_tokens + history_tokens + user_tokens
        
        # 预估缓存命中情况
        likely_hit = summary_tokens >= CACHE_BREAKPOINT_THRESHOLD
        
        cost_info = self.tracker.estimate_cost_with_cache(
            model_id,
            system_tokens + summary_tokens,  # 缓存部分
            history_tokens + user_tokens,    # 非缓存部分
            likely_hit,
        )

        return {
            "system_tokens": system_tokens,
            "summary_tokens": summary_tokens,
            "history_tokens": history_tokens,
            "user_tokens": user_tokens,
            "total_tokens": total,
            "cached_tokens": cost_info["cached_tokens"],
            "estimated_cost": cost_info["estimated_input_cost"],
            "savings_percent": cost_info["savings_percent"],
            "cache_hit": likely_hit,
        }

    def get_compaction_params(self, model_id: str) -> dict:
        """
        获取 Compaction API 兜底参数 (PRD v3)
        """
        return {
            "betas": ["compact-2026-01-12"],
            "context_management": {
                "edits": [{
                    "type": "compact_20260112",
                    "trigger": {"type": "input_tokens", "value": COMPACTION_TRIGGER_TOKENS}
                }]
            }
        }

    def _build_system_text(self, system_prompt: str, doc_context: str) -> str:
        """构建系统提示文本"""
        parts = []
        if system_prompt.strip():
            parts.append(system_prompt.strip())
        if doc_context.strip():
            parts.append("\n\n<project_knowledge>\n" + doc_context + "\n</project_knowledge>")
        if not parts:
            parts.append("You are a helpful AI assistant.")
        return "\n\n".join(parts)

    def _get_recent_messages(self, messages: list[Message], turns: int) -> list[Message]:
        """获取最近 N 轮对话"""
        if not messages:
            return []
        
        # 每轮包含 user + assistant 两条消息
        max_msgs = turns * 2
        return messages[-max_msgs:] if len(messages) > max_msgs else messages

    def _fit_history(self, messages: list[Message], token_budget: int) -> list[Message]:
        """选择适合 token 预算的消息，从最近往回选择"""
        if not messages:
            return []

        selected = []
        tokens_used = 0

        for msg in reversed(messages):
            msg_tokens = self.tracker.estimate_tokens(msg.content)
            if tokens_used + msg_tokens > token_budget:
                break
            selected.insert(0, msg)
            tokens_used += msg_tokens

        # 确保以 user 消息开始 (API 要求)
        while selected and selected[0].role == "assistant":
            selected.pop(0)

        # 限制最大消息数
        max_msgs = MAX_HISTORY_TURNS * 2
        if len(selected) > max_msgs:
            selected = selected[-max_msgs:]
            while selected and selected[0].role == "assistant":
                selected.pop(0)

        log.debug("History: %d/%d messages selected (%d tokens)",
                  len(selected), len(messages), tokens_used)
        return selected

    def _estimate_message_tokens(self, messages: list[dict]) -> int:
        """估算消息列表的 token 数"""
        total = 0
        for msg in messages:
            content = msg["content"]
            if isinstance(content, str):
                total += self.tracker.estimate_tokens(content)
            elif isinstance(content, list):
                # 包含附件的消息
                for block in content:
                    if block.get("type") == "text":
                        total += self.tracker.estimate_tokens(block.get("text", ""))
        return total
