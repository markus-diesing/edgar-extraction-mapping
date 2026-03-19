"""
Sections API — CRUD for section prompt specs stored in files/sections/section_specs.yaml.
Mounted at /api in main.py.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import sections.section_loader as section_loader

router = APIRouter(prefix="/sections", tags=["sections"])


class SectionUpdate(BaseModel):
    system_note: str | None = None
    search_headers: list[str] | None = None
    max_chars: int | None = None


class SystemNoteUpdate(BaseModel):
    system_note: str


@router.get("")
def list_sections():
    specs = section_loader.get_section_specs()
    return [
        {
            "name": name,
            "schema_keys": spec.get("schema_keys", []),
            "required_for": spec.get("required_for", []),
            "max_chars": spec.get("max_chars", 10000),
            "header_count": len(spec.get("search_headers", [])),
        }
        for name, spec in specs.items()
    ]


@router.get("/{section_name}")
def get_section(section_name: str):
    specs = section_loader.get_section_specs()
    if section_name not in specs:
        raise HTTPException(status_code=404, detail=f"Section '{section_name}' not found")
    return {"name": section_name, **specs[section_name]}


@router.put("/{section_name}")
def update_section(section_name: str, body: SectionUpdate):
    specs = section_loader.get_section_specs()
    if section_name not in specs:
        raise HTTPException(status_code=404, detail=f"Section '{section_name}' not found")
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    section_loader.save_section_spec(section_name, updates)
    return {"status": "saved", "section": section_name}


@router.put("/{section_name}/system_note")
def update_system_note(section_name: str, body: SystemNoteUpdate):
    specs = section_loader.get_section_specs()
    if section_name not in specs:
        raise HTTPException(status_code=404, detail=f"Section '{section_name}' not found")
    section_loader.save_section_spec(section_name, {"system_note": body.system_note})
    return {"status": "saved", "section": section_name}
