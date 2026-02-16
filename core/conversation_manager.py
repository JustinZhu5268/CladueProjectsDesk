"""Conversation and message management."""
from __future__ import annotations

import uuid
import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

from data.database import db

log = logging.getLogger(__name__)


@dataclass
class Message:
    id: str
    conversation_id: str
    role: str
    content: str
    thinking_content: str = ""
    attachments: list[dict] = field(default_factory=list)
    model_used: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    created_at: str = ""


@dataclass
class Conversation:
    id: str
    project_id: str
    title: str = "New Conversation"
    model_override: str | None = None
    created_at: str = ""
    updated_at: str = ""
    is_archived: bool = False
    # 压缩相关字段 (PRD v3)
    rolling_summary: str = ""
    last_compressed_msg_id: str | None = None
    summary_token_count: int = 0
    compress_after_turns: int = 10


class ConversationManager:
    """Manages conversations and messages."""

    # ── Conversations ──────────────────────────────────

    def create_conversation(self, project_id: str,
                            title: str = "New Conversation",
                            model_override: str | None = None) -> Conversation:
        cid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO conversations (id, project_id, title, model_override, created_at, updated_at, compress_after_turns)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, project_id, title, model_override, now, now, 10),
        )
        # Touch project updated_at
        db.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (now, project_id))
        log.info("Created conversation '%s' in project %s", title, project_id[:8])
        return Conversation(id=cid, project_id=project_id, title=title,
                            model_override=model_override, created_at=now, updated_at=now,
                            compress_after_turns=10)

    def get_conversation(self, conv_id: str) -> Conversation | None:
        row = db.execute_one("SELECT * FROM conversations WHERE id = ?", (conv_id,))
        return self._row_to_conv(row) if row else None

    def list_conversations(self, project_id: str,
                           include_archived: bool = False) -> list[Conversation]:
        if include_archived:
            rows = db.execute(
                "SELECT * FROM conversations WHERE project_id = ? ORDER BY updated_at DESC",
                (project_id,),
            )
        else:
            rows = db.execute(
                """SELECT * FROM conversations
                   WHERE project_id = ? AND is_archived = 0
                   ORDER BY updated_at DESC""",
                (project_id,),
            )
        return [self._row_to_conv(r) for r in rows]

    def rename_conversation(self, conv_id: str, new_title: str) -> None:
        db.execute("UPDATE conversations SET title = ? WHERE id = ?", (new_title, conv_id))
        log.info("Renamed conversation %s to '%s'", conv_id[:8], new_title)

    def archive_conversation(self, conv_id: str) -> None:
        db.execute("UPDATE conversations SET is_archived = 1 WHERE id = ?", (conv_id,))
        log.info("Archived conversation %s", conv_id[:8])

    def delete_conversation(self, conv_id: str) -> None:
        db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
        log.info("Deleted conversation %s", conv_id[:8])

    # ── Messages ───────────────────────────────────────

    def add_message(self, conversation_id: str, role: str, content: str,
                    thinking_content: str = "",
                    attachments: list[dict] | None = None,
                    model_used: str = "",
                    input_tokens: int = 0, output_tokens: int = 0,
                    cache_read_tokens: int = 0, cache_creation_tokens: int = 0,
                    cost_usd: float = 0.0) -> Message:
        mid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        att_json = json.dumps(attachments or [])
        db.execute(
            """INSERT INTO messages
               (id, conversation_id, role, content, thinking_content, attachments_json,
                model_used, input_tokens, output_tokens, cache_read_tokens,
                cache_creation_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (mid, conversation_id, role, content, thinking_content, att_json,
             model_used, input_tokens, output_tokens, cache_read_tokens,
             cache_creation_tokens, cost_usd, now),
        )
        # Touch conversation
        db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?",
                   (now, conversation_id))
        log.debug("Saved %s message (%d in / %d out tokens) in conv %s",
                  role, input_tokens, output_tokens, conversation_id[:8])
        return Message(
            id=mid, conversation_id=conversation_id, role=role, content=content,
            thinking_content=thinking_content, attachments=attachments or [],
            model_used=model_used, input_tokens=input_tokens, output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens, cache_creation_tokens=cache_creation_tokens,
            cost_usd=cost_usd, created_at=now,
        )

    def get_messages(self, conversation_id: str, limit: int = 0) -> list[Message]:
        if limit > 0:
            rows = db.execute(
                """SELECT * FROM (
                     SELECT * FROM messages WHERE conversation_id = ?
                     ORDER BY created_at DESC LIMIT ?
                   ) sub ORDER BY created_at ASC""",
                (conversation_id, limit),
            )
        else:
            rows = db.execute(
                "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC",
                (conversation_id,),
            )
        return [self._row_to_msg(r) for r in rows]

    def get_conversation_stats(self, conversation_id: str) -> dict:
        """Get token usage stats for a conversation."""
        row = db.execute_one(
            """SELECT
                 COUNT(*) as msg_count,
                 COALESCE(SUM(input_tokens), 0) as total_input,
                 COALESCE(SUM(output_tokens), 0) as total_output,
                 COALESCE(SUM(cache_read_tokens), 0) as total_cache_read,
                 COALESCE(SUM(cache_creation_tokens), 0) as total_cache_create,
                 COALESCE(SUM(cost_usd), 0.0) as total_cost
               FROM messages WHERE conversation_id = ?""",
            (conversation_id,),
        )
        if row:
            return dict(row)
        return {"msg_count": 0, "total_input": 0, "total_output": 0,
                "total_cache_read": 0, "total_cache_create": 0, "total_cost": 0.0}

    def get_project_stats(self, project_id: str) -> dict:
        """Get total token stats across all conversations in a project."""
        row = db.execute_one(
            """SELECT
                 COUNT(DISTINCT c.id) as conv_count,
                 COUNT(m.id) as msg_count,
                 COALESCE(SUM(m.input_tokens), 0) as total_input,
                 COALESCE(SUM(m.output_tokens), 0) as total_output,
                 COALESCE(SUM(m.cache_read_tokens), 0) as total_cache_read,
                 COALESCE(SUM(m.cost_usd), 0.0) as total_cost
               FROM conversations c
               LEFT JOIN messages m ON m.conversation_id = c.id
               WHERE c.project_id = ?""",
            (project_id,),
        )
        if row:
            return dict(row)
        return {"conv_count": 0, "msg_count": 0, "total_input": 0,
                "total_output": 0, "total_cache_read": 0, "total_cost": 0.0}

    # ── Private ────────────────────────────────────────

    def _row_to_conv(self, row) -> Conversation:
        return Conversation(
            id=row["id"], project_id=row["project_id"],
            title=row["title"], model_override=row["model_override"],
            created_at=row["created_at"], updated_at=row["updated_at"],
            is_archived=bool(row["is_archived"]),
            # 压缩相关字段 (PRD v3)
            rolling_summary=row.get("rolling_summary") or "",
            last_compressed_msg_id=row.get("last_compressed_msg_id"),
            summary_token_count=row.get("summary_token_count") or 0,
            compress_after_turns=row.get("compress_after_turns") or 10,
        )

    # ── Compression Methods ───────────────────────────

    def update_rolling_summary(self, conversation_id: str, summary: str, 
                                last_msg_id: str, token_count: int) -> None:
        """更新对话的滚动摘要"""
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """UPDATE conversations 
               SET rolling_summary = ?, last_compressed_msg_id = ?, 
                   summary_token_count = ?, updated_at = ?
               WHERE id = ?""",
            (summary, last_msg_id, token_count, now, conversation_id),
        )
        log.debug("Updated rolling summary for conv %s: %d tokens", 
                  conversation_id[:8], token_count)

    def reset_rolling_summary(self, conversation_id: str) -> None:
        """重置对话摘要（清除所有压缩历史）"""
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """UPDATE conversations 
               SET rolling_summary = '', last_compressed_msg_id = NULL, 
                   summary_token_count = 0, updated_at = ?
               WHERE id = ?""",
            (now, conversation_id),
        )
        log.info("Reset rolling summary for conversation %s", conversation_id[:8])

    def get_uncompressed_messages(self, conversation_id: str) -> list[Message]:
        """获取未压缩的消息（用于压缩）"""
        conv = self.get_conversation(conversation_id)
        if not conv or not conv.last_compressed_msg_id:
            return self.get_messages(conversation_id)
        
        # 返回 last_compressed_msg_id 之后的消息
        all_msgs = self.get_messages(conversation_id)
        for i, msg in enumerate(all_msgs):
            if msg.id == conv.last_compressed_msg_id:
                return all_msgs[i+1:]
        return all_msgs

    def get_compression_stats(self, conversation_id: str) -> dict:
        """获取对话的压缩统计信息"""
        conv = self.get_conversation(conversation_id)
        if not conv:
            return {"has_summary": False, "summary_tokens": 0, "uncompressed_count": 0}
        
        uncompressed = self.get_uncompressed_messages(conversation_id)
        # 每条消息算一轮 (user + assistant 算2条消息)
        turns = len(uncompressed) // 2
        
        return {
            "has_summary": bool(conv.rolling_summary),
            "summary_tokens": conv.summary_token_count,
            "uncompressed_count": len(uncompressed),
            "uncompressed_turns": turns,
            "compress_after_turns": conv.compress_after_turns,
            "should_compress": turns >= conv.compress_after_turns,
        }

    def _row_to_msg(self, row) -> Message:
        att = []
        try:
            att = json.loads(row["attachments_json"] or "[]")
        except json.JSONDecodeError:
            pass
        return Message(
            id=row["id"], conversation_id=row["conversation_id"],
            role=row["role"], content=row["content"],
            thinking_content=row["thinking_content"] or "",
            attachments=att, model_used=row["model_used"] or "",
            input_tokens=row["input_tokens"] or 0,
            output_tokens=row["output_tokens"] or 0,
            cache_read_tokens=row["cache_read_tokens"] or 0,
            cache_creation_tokens=row["cache_creation_tokens"] or 0,
            cost_usd=row["cost_usd"] or 0.0,
            created_at=row["created_at"],
        )
