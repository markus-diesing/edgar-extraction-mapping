"""
Settings API — GET/PUT runtime settings stored in files/runtime_settings.yaml.
Mounted at /api in main.py → endpoints at /api/settings.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import settings_store

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    sectioned_extraction: bool | None = None
    section_merge_confidence_delta: float | None = None
    classification_gate_confidence: float | None = None


@router.get("")
def get_settings():
    return settings_store.get_settings()


@router.put("")
def update_settings(body: SettingsUpdate):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    # Validate ranges
    if "section_merge_confidence_delta" in updates:
        v = updates["section_merge_confidence_delta"]
        if not 0.0 <= v <= 1.0:
            raise HTTPException(status_code=422, detail="section_merge_confidence_delta must be 0–1")
    if "classification_gate_confidence" in updates:
        v = updates["classification_gate_confidence"]
        if not 0.0 <= v <= 1.0:
            raise HTTPException(status_code=422, detail="classification_gate_confidence must be 0–1")
    return settings_store.update_settings(updates)
