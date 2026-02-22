from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.app.services.search_service import get_search_service

router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/search")
async def faq_search(request: SearchRequest):
    """Semantic FAQ search using LlamaIndex + Ollama."""
    try:
        service = get_search_service()
        results = service.search(request.query, top_k=request.top_k)
        return {"query": request.query, "results": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))