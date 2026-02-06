"""
Rule Configuration Service — manages configurable thresholds for the prefill engine.

All numeric thresholds used in the prefill rule engine are stored in the
rule_config database table.  This service loads them into an in-memory cache
and provides fast typed access with fallback defaults.

Usage:
    from services.rule_config_service import RuleConfig as RC
    score = RC.get_int("urgency.baseline", 50)
"""

from database import get_db
from typing import Any


class RuleConfig:
    """Singleton-style config loader with in-memory cache."""

    _cache: dict[str, dict] = {}
    _loaded: bool = False

    # ── Loading ────────────────────────────────────────────────────────

    @classmethod
    def load(cls):
        """Load all configs from DB into cache."""
        db = get_db()
        try:
            rows = db.execute("SELECT * FROM rule_config").fetchall()
            cls._cache = {row["key"]: dict(row) for row in rows}
            cls._loaded = True
        except Exception:
            cls._loaded = True  # prevent retry loops if table missing
        finally:
            db.close()

    @classmethod
    def reload(cls):
        """Force reload from DB (call after updates)."""
        cls._loaded = False
        cls.load()

    @classmethod
    def _ensure_loaded(cls):
        if not cls._loaded:
            cls.load()

    # ── Getters ────────────────────────────────────────────────────────

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a config value by key."""
        cls._ensure_loaded()
        entry = cls._cache.get(key)
        if entry is None:
            return default
        return entry["value"]

    @classmethod
    def get_int(cls, key: str, default: int = 0) -> int:
        val = cls.get(key, default)
        return int(val) if val is not None else default

    @classmethod
    def get_float(cls, key: str, default: float = 0.0) -> float:
        val = cls.get(key, default)
        return float(val) if val is not None else default

    # ── Queries ────────────────────────────────────────────────────────

    @classmethod
    def get_all(cls) -> list[dict]:
        """Get all config entries, sorted by category + display_order."""
        cls._ensure_loaded()
        items = list(cls._cache.values())
        items.sort(key=lambda x: (x.get("category", ""), x.get("display_order", 0)))
        return items

    @classmethod
    def get_by_category(cls, category: str) -> list[dict]:
        """Get all config entries for a specific category."""
        cls._ensure_loaded()
        items = [v for v in cls._cache.values() if v.get("category") == category]
        items.sort(key=lambda x: x.get("display_order", 0))
        return items

    @classmethod
    def get_categories(cls) -> list[str]:
        """Get list of unique category names."""
        cls._ensure_loaded()
        return sorted(set(v.get("category", "") for v in cls._cache.values()))

    # ── Mutations ──────────────────────────────────────────────────────

    @classmethod
    def update(cls, key: str, value: float) -> bool:
        """Update a single config value in DB and cache."""
        db = get_db()
        try:
            cur = db.execute(
                "UPDATE rule_config SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                (value, key),
            )
            db.commit()
            if key in cls._cache:
                cls._cache[key]["value"] = value
            return cur.rowcount > 0
        finally:
            db.close()

    @classmethod
    def update_many(cls, updates: list[dict]) -> int:
        """Update multiple config values. Each dict must have 'key' and 'value'."""
        db = get_db()
        try:
            count = 0
            for u in updates:
                cur = db.execute(
                    "UPDATE rule_config SET value = ?, updated_at = CURRENT_TIMESTAMP WHERE key = ?",
                    (u["value"], u["key"]),
                )
                if cur.rowcount > 0:
                    count += 1
                if u["key"] in cls._cache:
                    cls._cache[u["key"]]["value"] = u["value"]
            db.commit()
            return count
        finally:
            db.close()

    @classmethod
    def reset_to_defaults(cls):
        """Reset all config values to their factory defaults by re-seeding."""
        db = get_db()
        try:
            db.execute("DELETE FROM rule_config")
            db.commit()
        finally:
            db.close()
        # Re-seed from database module
        from database import _seed_rule_config

        db = get_db()
        try:
            cursor = db.cursor()
            _seed_rule_config(cursor)
            db.commit()
        finally:
            db.close()
        cls.reload()
