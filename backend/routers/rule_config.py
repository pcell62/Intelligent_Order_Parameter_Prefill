"""
Rule Config Router — CRUD endpoints for the rule engine configuration.

GET  /api/rule-config/             → all configs
GET  /api/rule-config/categories   → category list
GET  /api/rule-config/category/{c} → configs for one category
PUT  /api/rule-config/             → bulk update
POST /api/rule-config/reset        → reset all to factory defaults
"""

from pydantic import BaseModel
from fastapi import APIRouter, HTTPException

from services.rule_config_service import RuleConfig

router = APIRouter()


class ConfigUpdate(BaseModel):
    key: str
    value: float


class BulkConfigUpdate(BaseModel):
    updates: list[ConfigUpdate]


@router.get("/")
async def get_all_configs():
    """Get all rule engine configuration values."""
    return RuleConfig.get_all()


@router.get("/categories")
async def get_categories():
    """Get list of config categories."""
    return RuleConfig.get_categories()


@router.get("/category/{category}")
async def get_category_configs(category: str):
    """Get all configs for a specific category."""
    items = RuleConfig.get_by_category(category)
    if not items:
        raise HTTPException(status_code=404, detail=f"No configs for category '{category}'")
    return items


@router.put("/")
async def update_configs(body: BulkConfigUpdate):
    """Update multiple config values at once."""
    count = RuleConfig.update_many([u.model_dump() for u in body.updates])
    return {"updated": count, "message": f"Updated {count} configuration values"}


@router.post("/reset")
async def reset_to_defaults():
    """Reset all configuration values to factory defaults."""
    RuleConfig.reset_to_defaults()
    return {"message": "All configurations reset to defaults"}
