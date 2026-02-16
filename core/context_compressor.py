"""
增量式滚动摘要系统 (PRD v3 核心创新)

该模块实现对话压缩功能，将长对话历史压缩为摘要，
大幅降低 API 调用成本。

核心设计原则：
1. 增量式压缩：每次只压缩最老的 K 轮，而非全部历史
2. 异步预压缩：在用户收到回复后后台执行，不阻塞主流程
3. 成本最低化：强制使用 Haiku 模型做压缩
4. 代码保护：压缩时保留代码函数签名和核心逻辑
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from config import (
    COMPRESS_AFTER_TURNS,
    COMPRESS_BATCH_SIZE,
    MAX_SUMMARY_TOKENS,
    SUMMARY_RECOMPRESS_THRESHOLD,
    MODELS,
)
from core.conversation_manager import ConversationManager, Message
from core.token_tracker import TokenTracker
from data.database import db

log = logging.getLogger(__name__)

# Haiku 模型用于压缩 (最低成本)
COMPRESS_MODEL = "claude-haiku-4-5-20251001"

# 压缩提示词模板
COMPRESS_SYSTEM_PROMPT = """You are a conversation summarizer for project '{project_name}'. 
Output ONLY the summary in the same language as the conversation. 
No preamble, no explanation."""

COMPRESS_USER_PROMPT_TEMPLATE = """请将以下对话压缩为简洁摘要。规则：
1. 保留所有关键决策和结论
2. 保留代码片段的函数签名和核心逻辑（不要只用自然语言概括代码）
3. 保留数据点、技术细节、专业术语原文
4. 保留用户偏好和约束条件
5. 删除客套、闲聊、重复内容
6. 摘要长度控制在 {max_tokens} tokens 以内

现有摘要:
{existing_summary}

新对话内容:
{conversation_turns}"""


@dataclass
class CompressionResult:
    """压缩结果"""
    success: bool
    new_summary: str
    tokens_saved: int = 0
    error: str = ""


class ContextCompressor:
    """
    增量式滚动摘要压缩机
    
    工作流程：
    1. 检查是否需要压缩 (未压缩轮次 >= N)
    2. 获取最老的 K 轮对话
    3. 调用 Haiku 生成摘要
    4. 更新数据库中的 rolling_summary
    5. 如果摘要过长 (>3000 tokens)，对摘要本身再压缩
    """

    def __init__(self):
        self.conv_mgr = ConversationManager()
        self.token_tracker = TokenTracker()

    def should_compress(self, conversation_id: str) -> bool:
        """
        判断是否需要触发压缩
        
        当未压缩的对话轮次超过配置的阈值时返回 True
        """
        conv = self.conv_mgr.get_conversation(conversation_id)
        if not conv:
            return False
        
        # 获取未压缩的消息
        uncompressed = self.conv_mgr.get_uncompressed_messages(conversation_id)
        
        # 每轮包含 user + assistant 两条消息
        uncompressed_turns = len(uncompressed) // 2
        
        threshold = conv.compress_after_turns or COMPRESS_AFTER_TURNS
        should = uncompressed_turns >= threshold
        
        log.debug(
            "Compression check for conv %s: %d turns >= %d threshold = %s",
            conversation_id[:8], uncompressed_turns, threshold, should
        )
        
        return should

    def compress(self, conversation_id: str, project_name: str = "Project") -> CompressionResult:
        """
        执行增量压缩
        
        1. 获取未压缩的消息中最老的 K 轮
        2. 调用 Haiku 生成摘要
        3. 追加到现有 rolling_summary
        4. 更新数据库
        5. 如果摘要过长，递归压缩
        """
        conv = self.conv_mgr.get_conversation(conversation_id)
        if not conv:
            return CompressionResult(success=False, new_summary="", error="Conversation not found")

        # 获取未压缩的消息
        all_messages = self.conv_mgr.get_messages(conversation_id)
        
        # 确定哪些消息需要压缩
        if conv.last_compressed_msg_id:
            # 找到 last_compressed_msg_id 之后的消息
            for i, msg in enumerate(all_messages):
                if msg.id == conv.last_compressed_msg_id:
                    uncompressed = all_messages[i+1:]
                    break
            else:
                uncompressed = []
        else:
            # 从未压缩过，取最老的 K 轮
            uncompressed = all_messages

        # 按批次压缩 (K 轮 = K*2 条消息)
        batch_size = COMPRESS_BATCH_SIZE * 2
        oldest_batch = uncompressed[:batch_size]
        
        if not oldest_batch:
            return CompressionResult(success=False, new_summary=conv.rolling_summary, 
                                    error="No messages to compress")

        # 计算压缩前 token 数
        tokens_before = sum(
            self.token_tracker.estimate_tokens(msg.content) 
            for msg in oldest_batch
        )

        # 格式化对话内容
        conv_turns = self._format_conversation_turns(oldest_batch)
        
        # 构建压缩提示
        system_prompt = COMPRESS_SYSTEM_PROMPT.format(project_name=project_name)
        user_prompt = COMPRESS_USER_PROMPT_TEMPLATE.format(
            max_tokens=MAX_SUMMARY_TOKENS,
            existing_summary=conv.rolling_summary or "(无)",
            conversation_turns=conv_turns,
        )

        # 调用 API 压缩 (需要同步调用，因为是在 worker 线程中)
        try:
            summary = self._call_compress_api(system_prompt, user_prompt)
        except Exception as e:
            log.error("Compression API failed: %s", e)
            return CompressionResult(
                success=False, 
                new_summary=conv.rolling_summary,
                error=str(e)
            )

        # 计算压缩后 token 数
        tokens_after = self.token_tracker.estimate_tokens(summary)
        tokens_saved = max(0, tokens_before - tokens_after)

        # 追加到现有摘要
        if conv.rolling_summary:
            new_summary = conv.rolling_summary + "\n\n" + summary
        else:
            new_summary = summary

        # 检查是否需要重新压缩摘要
        summary_tokens = self.token_tracker.estimate_tokens(new_summary)
        if summary_tokens > SUMMARY_RECOMPRESS_THRESHOLD:
            log.info("Summary exceeds threshold (%d > %d), re-compressing", 
                     summary_tokens, SUMMARY_RECOMPRESS_THRESHOLD)
            new_summary = self._recompress_summary(new_summary, project_name)
            summary_tokens = self.token_tracker.estimate_tokens(new_summary)

        # 更新数据库
        last_msg = oldest_batch[-1] if oldest_batch else None
        self.conv_mgr.update_rolling_summary(
            conversation_id=conversation_id,
            summary=new_summary,
            last_msg_id=last_msg.id if last_msg else "",
            token_count=summary_tokens,
        )

        log.info(
            "Compression complete for conv %s: %d -> %d tokens (saved %d)",
            conversation_id[:8], tokens_before, summary_tokens, tokens_saved
        )

        return CompressionResult(
            success=True,
            new_summary=new_summary,
            tokens_saved=tokens_saved,
        )

    def _call_compress_api(self, system_prompt: str, user_prompt: str) -> str:
        """
        调用 Haiku API 进行压缩
        
        注意：这是一个同步调用，应该在后台线程中执行
        """
        from api.claude_client import ClaudeClient
        from utils.key_manager import KeyManager
        
        key_mgr = KeyManager()
        default = key_mgr.get_default_key()
        
        if not default:
            raise RuntimeError("No API key configured for compression")
        
        _, api_key = default
        client = ClaudeClient()
        client.configure(api_key)

        # 同步调用 Haiku
        messages = [{"role": "user", "content": user_prompt}]
        system = [{"type": "text", "text": system_prompt}]
        
        full_text = ""
        for event in client.stream_message(
            messages=messages,
            system_content=system,
            model=COMPRESS_MODEL,
            max_tokens=MAX_SUMMARY_TOKENS,
        ):
            if event.type == "text":
                full_text += event.text
            elif event.type == "error":
                raise RuntimeError(f"Compression error: {event.error}")
            elif event.type == "done":
                break

        return full_text.strip()

    def _format_conversation_turns(self, messages: list[Message]) -> str:
        """将消息格式化为压缩提示"""
        parts = []
        for msg in messages:
            role = "User" if msg.role == "user" else "Assistant"
            parts.append(f"[{role}]: {msg.content}")
        return "\n\n".join(parts)

    def _recompress_summary(self, summary: str, project_name: str) -> str:
        """
        对摘要本身进行再压缩
        
        当摘要超过 SUMMARY_RECOMPRESS_THRESHOLD tokens 时调用
        """
        system_prompt = COMPRESS_SYSTEM_PROMPT.format(project_name=project_name)
        user_prompt = COMPRESS_USER_PROMPT_TEMPLATE.format(
            max_tokens=MAX_SUMMARY_TOKENS,
            existing_summary="",
            conversation_turns=summary,
        )

        try:
            return self._call_compress_api(system_prompt, user_prompt)
        except Exception as e:
            log.warning("Summary re-compression failed: %s, using original", e)
            return summary

    def estimate_compression_cost(self, messages: list[Message]) -> float:
        """预估压缩成本"""
        total_tokens = sum(
            self.token_tracker.estimate_tokens(msg.content) 
            for msg in messages
        )
        
        model = MODELS.get(COMPRESS_MODEL)
        if not model:
            model = MODELS["claude-haiku-4-5-20251001"]
        
        # 输入价格 (假设压缩输出约 30% 的输入)
        estimated_output = total_tokens * 0.3
        cost = (
            total_tokens * model.input_price / 1_000_000 +
            estimated_output * model.output_price / 1_000_000
        )
        
        return round(cost, 4)


class CompressionWorker:
    """
    后台压缩工作线程 (QThread)
    
    PRD v3 建议：在用户收到回复后异步执行压缩，不阻塞主流程
    """

    def __init__(self, conversation_id: str, project_name: str = "Project"):
        self.conversation_id = conversation_id
        self.project_name = project_name
        self.compressor = ContextCompressor()
        self._result: Optional[CompressionResult] = None

    def run(self) -> CompressionResult:
        """执行压缩并返回结果"""
        try:
            if not self.compressor.should_compress(self.conversation_id):
                log.debug("No compression needed for %s", self.conversation_id[:8])
                return CompressionResult(success=True, new_summary="", tokens_saved=0)

            self._result = self.compressor.compress(
                self.conversation_id, 
                self.project_name
            )
            return self._result

        except Exception as e:
            log.exception("Compression worker failed")
            return CompressionResult(
                success=False, 
                new_summary="",
                error=str(e)
            )
