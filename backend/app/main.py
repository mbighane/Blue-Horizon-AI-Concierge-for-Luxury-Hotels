"""
FastAPI main application entry point for Blue Horizon.
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Import routers
# from backend.app.api import health, chat, services
from backend.app.api import chat, health, services
from backend.app.api import nl2sql
from backend.app.agents.openai_chat_agent import OpenAIChatAgent
from backend.app.config import Settings

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

# Initialize settings
settings = Settings()

# Initialize OpenAI Chat Agent
chat_agent = OpenAIChatAgent(settings)

# Include routers
# app.include_router(health.router, prefix="/api", tags=["Health"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat"])
app.include_router(services.router, prefix="/api/services", tags=["Services"])
app.include_router(nl2sql.router, prefix="/api/nl2sql", tags=["NL2SQL"])

# Chat endpoint with session memory and context tracking
@app.post("/api/chat/agent")
async def chat_with_agent(request: Request):
    data = await request.json()
    user_id = data.get("user_id")
    user_message = data.get("message")

    if not user_id or not user_message:
        return JSONResponse(content={"error": "user_id and message are required"}, status_code=400)

    # Process user message with session memory
    response = chat_agent.process_message(user_id, user_message)
    return {"response": response}

# Root endpoint
@app.get("/")
async def root():
    return {
        "message": "Welcome to Blue Horizon - AI Concierge for Luxury Hotels",
        "version": "0.1.0"
    }

# @app.get("/health")
# async def health_check():
#     return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
