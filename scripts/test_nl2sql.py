"""Test script for NL2SQL service."""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.services.nl2sql_service import NL2SQLService


def main():
    """Test NL2SQL service with sample queries."""
    
    print("=" * 60)
    print("NL2SQL Service Test")
    print("=" * 60)
    
    # Initialize service - will try OpenAI, fallback to Ollama if it fails
    print("\nInitializing NL2SQL Service...")
    agent = NL2SQLService(
        model="gpt-4o-mini",  # Try OpenAI first
        use_ollama=False,        # Don't force Ollama
        fallback_to_ollama=True  # Auto-fallback to llama3 if OpenAI fails
    )
    
    # Test queries
    test_questions = [
        # "How many rooms are Available?"
        #  ,"What are the most expensive rooms?",
         #"Show me all bookings for this month",
         "Which guests have made the most bookings?",
    ]
    
    for question in test_questions:
        print(f"\n{'='*60}")
        print(f"❓ Question: {question}")
        print("-" * 60)
        
        try:
            result = agent.query(question)
            
            print(f"🔍 SQL: {result['sql_query']}")
            
            if result['success']:
                print(f"✓ Results: {result['row_count']} rows")
                if result['rows']:
                    for i, row in enumerate(result['rows'][:3], 1):
                        print(f"   Row {i}: {row}")
                
                # Get explanation
                explanation = agent.explain_results(question, result)
                print(f"\n💡 Explanation: {explanation}")
            else:
                print(f"✗ Error: {result.get('error')}")
        
        except Exception as e:
            print(f"✗ Exception: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()