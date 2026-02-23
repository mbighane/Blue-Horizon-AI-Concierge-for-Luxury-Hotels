"""Database setup script for creating tables and initial data."""
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from backend.app.database import engine, Base
from backend.app.config import get_settings


def create_tables():
    """Create all database tables."""
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("✓ Tables created successfully!")


def test_connection():
    """Test database connection to Neon."""
    settings = get_settings()
    print(f"Testing connection to Neon database...")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            version = result.fetchone()[0]
            print(f"✓ Connected successfully!")
            print(f"PostgreSQL version: {version}")
            
            # Check if we're connected to Neon
            if "neon" in settings.database_url.lower():
                print("✓ Connected to Neon serverless PostgreSQL")
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        raise


def main():
    """Main setup function."""
    print("=" * 50)
    print("BlueHorizon Database Setup with Neon")
    print("=" * 50)
    
    test_connection()
    create_tables()
    
    print("\n" + "=" * 50)
    print("Setup completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    main()