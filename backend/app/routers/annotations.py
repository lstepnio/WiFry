"""Annotations router — notes and tags on data points."""

from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ..services import annotations

router = APIRouter(prefix="/api/v1/annotations", tags=["annotations"])


class CreateAnnotation(BaseModel):
    target_type: str = Field(..., description="capture, stream, device, scenario, general")
    target_id: str
    note: str
    tags: List[str] = Field(default_factory=list)


@router.post("", status_code=201)
async def add_annotation(req: CreateAnnotation):
    return annotations.add_annotation(req.target_type, req.target_id, req.note, req.tags)


@router.get("")
async def list_annotations(
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    tag: Optional[str] = None,
):
    return annotations.get_annotations(target_type, target_id, tag)


@router.delete("/{ann_id}")
async def delete_annotation(ann_id: str):
    annotations.delete_annotation(ann_id)
    return {"status": "ok"}
