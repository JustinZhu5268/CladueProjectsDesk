"""Builds the API request payload with prompt caching optimization."""
from __future__ import annotations

import logging

from config import MODELS, RESPONSE_TOKEN_RESERVE, MAX_HISTORY_TURNS, CONTEXT_USAGE_THRESHOLD
from core.document_processor import DocumentProcessor
from core.conversation_manager import ConversationManager, Message
from core.token_tracker import TokenTracker

log = logging.getLogger(__name__)


class ContextBuilder:
    """Assembles system prompt + documents + conversation history for API calls."""

    def __init__(self) -> None:
        self.doc_processor = DocumentProcessor()
        self.conv_manager = ConversationManager()
        self.tracker = TokenTracker()

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
        Build the complete API request.
        
        Returns:
            (system_content, messages, estimated_tokens)
            - system_content: list of content blocks for the system parameter
            - messages: list of message dicts for the messages parameter
            - estimated_tokens: estimated total input tokens
        """
        model = MODELS.get(model_id, MODELS["claude-sonnet-4-5-20250929"])
        context_limit = model.context_window
        budget = int(context_limit * CONTEXT_USAGE_THRESHOLD) - RESPONSE_TOKEN_RESERVE

        # 1. Build system content (cached)
        doc_context = self.doc_processor.get_project_context(project_id)
        system_text = self._build_system_text(system_prompt, doc_context)
        system_tokens = self.tracker.estimate_tokens(system_text)

        system_content = [
            {
                "type": "text",
                "text": system_text,
                "cache_control": {"type": "ephemeral"},
            }
        ]

        log.debug("System prompt: %d tokens (cached)", system_tokens)

        # 2. Build conversation history
        remaining_budget = budget - system_tokens
        if remaining_budget < 1000:
            log.warning("Very little room for conversation (%d tokens left)", remaining_budget)
            remaining_budget = max(remaining_budget, 1000)

        all_messages = self.conv_manager.get_messages(conversation_id)
        history = self._fit_history(all_messages, remaining_budget)

        # 3. Build message list
        messages = []
        for msg in history:
            content: str | list[dict] = msg.content
            # We keep it simple - just text content for history
            messages.append({"role": msg.role, "content": msg.content})

        # 4. Append current user message
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

        # 5. Estimate total
        msg_tokens = sum(self.tracker.estimate_tokens(
            m["content"] if isinstance(m["content"], str) else m["content"][0]["text"]
        ) for m in messages)
        total_estimated = system_tokens + msg_tokens

        log.info(
            "Context built: system=%d, messages=%d (%d turns), total=%d/%d tokens",
            system_tokens, msg_tokens, len(messages), total_estimated, context_limit,
        )

        return system_content, messages, total_estimated

    def estimate_request(
        self, project_id: str, conversation_id: str,
        user_message: str, system_prompt: str, model_id: str,
    ) -> dict:
        """Quick token/cost estimate without building full request."""
        doc_context = self.doc_processor.get_project_context(project_id)
        system_text = self._build_system_text(system_prompt, doc_context)
        system_tokens = self.tracker.estimate_tokens(system_text)

        all_messages = self.conv_manager.get_messages(conversation_id)
        history_tokens = sum(
            self.tracker.estimate_tokens(m.content) for m in all_messages
        )
        user_tokens = self.tracker.estimate_tokens(user_message)

        total = system_tokens + history_tokens + user_tokens
        cost = self.tracker.estimate_input_cost(model_id, total)

        return {
            "system_tokens": system_tokens,
            "history_tokens": history_tokens,
            "user_tokens": user_tokens,
            "total_tokens": total,
            "estimated_cost": cost,
        }

    def _build_system_text(self, system_prompt: str, doc_context: str) -> str:
        """Combine system prompt and document context."""
        parts = []
        if system_prompt.strip():
            parts.append(system_prompt.strip())
        if doc_context.strip():
            parts.append("\n\n<project_knowledge>\n" + doc_context + "\n</project_knowledge>")
        if not parts:
            parts.append("You are a helpful AI assistant.")
        return "\n\n".join(parts)

    def _fit_history(self, messages: list[Message], token_budget: int) -> list[Message]:
        """Select messages that fit within token budget, most recent first."""
        if not messages:
            return []

        # Start from most recent, work backwards
        selected = []
        tokens_used = 0

        for msg in reversed(messages):
            msg_tokens = self.tracker.estimate_tokens(msg.content)
            if tokens_used + msg_tokens > token_budget:
                break
            selected.insert(0, msg)
            tokens_used += msg_tokens

        # Ensure we start with a user message (API requirement)
        while selected and selected[0].role == "assistant":
            selected.pop(0)

        # Cap at MAX_HISTORY_TURNS
        max_msgs = MAX_HISTORY_TURNS * 2
        if len(selected) > max_msgs:
            selected = selected[-max_msgs:]
            while selected and selected[0].role == "assistant":
                selected.pop(0)

        log.debug("History: %d/%d messages selected (%d tokens)",
                  len(selected), len(messages), tokens_used)
        return selected
