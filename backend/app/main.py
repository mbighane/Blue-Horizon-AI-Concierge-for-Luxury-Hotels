"""
FastAPI main application entry point for Blue Horizon.
"""
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

# Add the project root directory to sys.path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))

# Import routers
from backend.app.api import faq, concierge, nl2sql

# Create FastAPI app
app = FastAPI(
    title="Blue Horizon API",
    description="AI-Powered Hospitality Concierge System",
    version="0.1.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(faq.router, prefix="/api/faq", tags=["FAQ"])
app.include_router(nl2sql.router, prefix="/api", tags=["NL2SQL"])
app.include_router(concierge.router, prefix="/api/concierge", tags=["Concierge"])

# Suppress browser favicon 404
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to Blue Horizon - AI Concierge for Luxury Hotels",
        "version": "0.1.0"
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
