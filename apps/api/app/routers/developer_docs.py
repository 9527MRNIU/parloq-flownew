from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.deps import CurrentUser
from app.developer_docs import catalog, page_content, page_metadata


router = APIRouter(prefix="/api/developer-docs", tags=["developer-docs"])


@router.get("")
def developer_docs_catalog(_current_user: CurrentUser) -> dict:
    return {
        "data": {
            "defaultPage": "overview",
            "sections": catalog(),
        }
    }


@router.get("/{slug}")
def developer_doc_page(slug: str, _current_user: CurrentUser) -> dict:
    metadata = page_metadata(slug)
    content = page_content(slug)
    if metadata is None or content is None:
        raise HTTPException(status_code=404, detail="文档页面不存在")
    return {"data": {"page": metadata, "content": content}}

