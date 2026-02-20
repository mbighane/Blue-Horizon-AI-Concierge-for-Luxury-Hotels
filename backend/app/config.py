from pydantic import ConfigDict
from pydantic_settings import BaseSettings
from functools import lru_cache
import os
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Database Settings
    database_url: str
    db_host: Optional[str] = None
    db_port: int = 5432
    db_name: Optional[str] = None
    db_user: Optional[str] = None
    db_password: Optional[str] = None
    
    # Redis Settings
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: Optional[str] = None
    
   # OpenAI Settings
    openai_api_key: str = ""  # Set in .env: OPENAI_API_KEY=sk-...
    openai_model: str = "gpt-3.5-turbo"  # Default model
    openai_text_embedding_model: str = "text-embedding-3-small"  # Default text embedding model
    
    # Ollama Settings
    ollama_model: str = "llama3"  # Default Ollama LLM model
    ollama_embed_model: str = "mxbai-embed-large"  # Dedicated embedding model
    ollama_api_url: str = "http://localhost:11434/api/generate"  # Default API URL
    ollama_base_url: str = "http://localhost:11434"  # Default base URL

    # Application Settings
    env: str = "development"
    debug: bool = True

   # CSV Data Paths
    #rooms_csv: Optional[str] = None
    #bookings_csv: Optional[str] = None
    #guests_csv: Optional[str] = None
    # Data Directories
    data_dir: Optional[str] = "D:\\Manisha\\IKCapStoneProject\\Blue Horizon Data"  # Default data directory
    faq_data_dir: Optional[str] = "D:\\Manisha\\IKCapStoneProject\\Blue Horizon Data\\FAQData"
    
    
    model_config = ConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra='ignore'  # Ignore extra fields from .env
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()