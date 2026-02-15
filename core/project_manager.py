"""Project CRUD operations."""
from __future__ import annotations

import json
import uuid
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field

from data.database import db

log = logging.getLogger(__name__)


@dataclass
class Project:
    id: str
    name: str
    system_prompt: str = ""
    default_model: str = "claude-haiku-4-5-20251001"
    api_key_id: str | None = None
    created_at: str = ""
    updated_at: str = ""
    settings: dict = field(default_factory=dict)


class ProjectManager:
    """Manages project lifecycle."""

    def create(self, name: str, model: str = "claude-sonnet-4-5-20250929",
               system_prompt: str = "", api_key_id: str | None = None) -> Project:
        pid = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """INSERT INTO projects (id, name, system_prompt, default_model, api_key_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, system_prompt, model, api_key_id, now, now),
        )
        log.info("Created project: %s (%s)", name, pid[:8])
        return Project(id=pid, name=name, system_prompt=system_prompt,
                       default_model=model, api_key_id=api_key_id,
                       created_at=now, updated_at=now)

    def get(self, project_id: str) -> Project | None:
        row = db.execute_one("SELECT * FROM projects WHERE id = ?", (project_id,))
        if row is None:
            return None
        return self._row_to_project(row)

    def list_all(self) -> list[Project]:
        rows = db.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        return [self._row_to_project(r) for r in rows]

    def update(self, project_id: str, **kwargs) -> None:
        allowed = {"name", "system_prompt", "default_model", "api_key_id", "settings_json"}
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed:
                if k == "settings_json" and isinstance(v, dict):
                    v = json.dumps(v)
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return
        sets.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(project_id)
        db.execute(f"UPDATE projects SET {', '.join(sets)} WHERE id = ?", tuple(params))
        log.info("Updated project %s: %s", project_id[:8], list(kwargs.keys()))

    def delete(self, project_id: str) -> None:
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        log.info("Deleted project %s", project_id[:8])

    def _row_to_project(self, row) -> Project:
        settings = {}
        sj = row["settings_json"]
        if sj:
            try:
                settings = json.loads(sj)
            except json.JSONDecodeError:
                pass
        return Project(
            id=row["id"], name=row["name"],
            system_prompt=row["system_prompt"] or "",
            default_model=row["default_model"],
            api_key_id=row["api_key_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            settings=settings,
        )
