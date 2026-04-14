import json

from fastapi import APIRouter, HTTPException, Query

from tools.skills_tool import skill_view, skills_list


router = APIRouter(prefix="/api/skills", tags=["skills"])


def _skills_payload(category: str | None = None) -> dict:
    result = json.loads(skills_list(category=category))
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Failed to list skills"))
    return result


@router.get("")
async def list_skills(category: str | None = Query(None)) -> dict:
    return _skills_payload(category=category)


@router.get("/categories")
async def list_skill_categories() -> dict:
    result = _skills_payload()
    return {
        "success": True,
        "categories": result.get("categories", []),
        "count": len(result.get("categories", [])),
    }


@router.get("/{name:path}")
async def get_skill(name: str, file_path: str | None = Query(None)) -> dict:
    result = json.loads(skill_view(name=name, file_path=file_path))
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", f"Skill '{name}' not found"))
    return result
