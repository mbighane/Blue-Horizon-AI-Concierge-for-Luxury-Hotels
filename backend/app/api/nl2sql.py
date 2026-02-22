"""NL2SQL API endpoints."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from backend.app.services.nl2sql_service import NL2SQLService

router = APIRouter(prefix="/nl2sql", tags=["NL2SQL"])

# Initialize service
nl2sql_agent = NL2SQLService()


class QueryRequest(BaseModel):
    """Request model for natural language query."""
    question: str


class QueryResponse(BaseModel):
    """Response model for query results."""
    natural_query: str
    sql_query: str
    success: bool
    columns: list
    rows: list
    row_count: int = 0
    error: str = None
    explanation: str = None


@router.post("/query", response_model=QueryResponse)
async def execute_nl2sql_query(request: QueryRequest):
    """
    Convert natural language to SQL and execute.
    
    Args:
        request: QueryRequest with natural language question
        
    Returns:
        Query results with SQL and data
    """
    try:
        # Execute NL2SQL query
        results = nl2sql_agent.query(request.question)
        
        # Generate explanation
        if results.get("success"):
            explanation = nl2sql_agent.explain_results(request.question, results)
            results["explanation"] = explanation
        
        return QueryResponse(**results)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))