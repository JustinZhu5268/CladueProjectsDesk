"""Secure API key storage using system keyring."""
from __future__ import annotations

import uuid
import logging

from config import KEYRING_SERVICE
from data.database import db

log = logging.getLogger(__name__)

class KeyManager:
    """Manages API key profiles with secure storage."""

    def _get_keyring(self):
        try:
            import keyring
            return keyring
        except ImportError:
            log.warning("keyring not available")
            return None

    def add_key(self, label: str, api_key: str) -> str:
        """Store a new API key. Returns the key profile ID."""
        profile_id = str(uuid.uuid4())
        key_ref = f"claude_station_{profile_id}"
        
        kr = self._get_keyring()
        
        # 修复：先检查是否应设为默认
        existing = db.execute_one("SELECT COUNT(*) as c FROM api_keys")
        is_default = 1 if (existing is None or existing["c"] == 0) else 0
        
        if kr:
            # 使用keyring安全存储
            kr.set_password(KEYRING_SERVICE, key_ref, api_key)
            log.info("API key stored in system keyring: %s", label)
            db.execute(
                "INSERT INTO api_keys (id, label, key_ref, is_default) VALUES (?, ?, ?, ?)",
                (profile_id, label, key_ref, is_default),
            )
        else:
            # Fallback：仅当keyring不可用时使用数据库（不安全，但可用）
            log.warning("Storing API key in database (keyring unavailable)")
            db.execute(
                "INSERT INTO api_keys (id, label, key_ref, is_default) VALUES (?, ?, ?, ?)",
                (profile_id, label, f"INSECURE:{api_key}", is_default),
            )
        
        return profile_id

    def get_key(self, profile_id: str) -> str | None:
        """Retrieve the API key for a profile."""
        row = db.execute_one("SELECT key_ref FROM api_keys WHERE id = ?", (profile_id,))
        if not row:
            return None
        key_ref = row["key_ref"]

        if key_ref.startswith("INSECURE:"):
            return key_ref[9:]

        kr = self._get_keyring()
        if kr:
            return kr.get_password(KEYRING_SERVICE, key_ref)
        return None

    def get_default_key(self) -> tuple[str, str] | None:
        """Get the default API key. Returns (profile_id, api_key) or None."""
        row = db.execute_one("SELECT id FROM api_keys WHERE is_default = 1 LIMIT 1")
        if not row:
            # Try any key
            row = db.execute_one("SELECT id FROM api_keys LIMIT 1")
        if not row:
            return None
        
        key = self.get_key(row["id"])
        if key:
            return row["id"], key
        return None

    def list_keys(self) -> list[dict]:
        """List all API key profiles (without the actual keys)."""
        rows = db.execute("SELECT id, label, is_default, created_at FROM api_keys ORDER BY created_at ASC")
        return [dict(r) for r in rows]

    def set_default(self, profile_id: str) -> None:
        """Set a key as the default."""
        db.execute("UPDATE api_keys SET is_default = 0")
        db.execute("UPDATE api_keys SET is_default = 1 WHERE id = ?", (profile_id,))
        log.info("Set default API key: %s", profile_id[:8])

    def delete_key(self, profile_id: str) -> None:
        """Delete an API key profile."""
        row = db.execute_one("SELECT key_ref FROM api_keys WHERE id = ?", (profile_id,))
        if row:
            key_ref = row["key_ref"]
            if not key_ref.startswith("INSECURE:"):
                kr = self._get_keyring()
                if kr:
                    try:
                        kr.delete_password(KEYRING_SERVICE, key_ref)
                    except Exception:
                        pass
            db.execute("DELETE FROM api_keys WHERE id = ?", (profile_id,))
            log.info("Deleted API key profile %s", profile_id[:8])

    def update_key(self, profile_id: str, new_key: str) -> None:
        """Update the API key for an existing profile."""
        row = db.execute_one("SELECT key_ref FROM api_keys WHERE id = ?", (profile_id,))
        if not row:
            return
        key_ref = row["key_ref"]

        if key_ref.startswith("INSECURE:"):
            db.execute("UPDATE api_keys SET key_ref = ? WHERE id = ?",
                      (f"INSECURE:{new_key}", profile_id))
        else:
            kr = self._get_keyring()
            if kr:
                kr.set_password(KEYRING_SERVICE, key_ref, new_key)
        log.info("Updated API key for profile %s", profile_id[:8])