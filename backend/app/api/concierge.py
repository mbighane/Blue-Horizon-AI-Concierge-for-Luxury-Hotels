"""Concierge agent API endpoint."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.app.agents.concierge_agent import ask_concierge, clear_session

router = APIRouter()


class ConciergeRequest(BaseModel):
    user_id: str
    message: str


class ConciergeResponse(BaseModel):
    user_id: str
    message: str
    response: str


@router.post("/ask", response_model=ConciergeResponse)
async def concierge_ask(request: ConciergeRequest):
    """
    Unified AI concierge endpoint.
    The agent automatically picks between SQL queries, FAQ search, and
    general conversation based on the user's question.
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        response = await ask_concierge(request.message, user_id=request.user_id)
        return ConciergeResponse(
            user_id=request.user_id,
            message=request.message,
            response=response,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/clear/{user_id}", status_code=204)
async def concierge_clear_session(user_id: str):
    """Clear the server-side conversation history for the given user session."""
    clear_session(user_id)
