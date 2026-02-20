"""Script to initialize vector search with hotel FAQ data from CSV files."""
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from backend.app.services.search_service import HotelFAQSearchService
from backend.app.config import get_settings


def main():
    """Setup vector search index from CSV files."""
    print("=" * 60)
    print("Hotel FAQ Vector Search Setup (CSV)")
    print("=" * 60)
    
    # Get settings
    settings = get_settings()
    faq_dir = settings.faq_data_dir
    
    print(f"\nFAQ Data Directory: {faq_dir}")
    
    # Initialize service
    search_service = HotelFAQSearchService()
    
    # Auto-discover all CSV files in the FAQ directory
    print(f"\nAuto-discovering CSV files from: {faq_dir}")
    search_service.create_index(
        data_dir=faq_dir,
        index_name="hotel_faq"
    )
    
    print("\n" + "=" * 60)
    print("✓ Vector search setup complete!")
    print("=" * 60)
    
    # Test search
    print("\n" + "=" * 60)
    print("Testing Search")
    print("=" * 60)
    
    test_queries = [
        "Can I bring my dog?"
        # ,
        # "What time can I check in?",
        # "Is there a pool?",
        # "Do you have free wifi?",
        # "Is breakfast included?",
    ]
    
    for query in test_queries:
        print(f"\n🔍 Query: '{query}'")
        print("-" * 60)
        
        try:
            results = search_service.search(query, top_k=1)
            
            if results:
                for i, result in enumerate(results, 1):
                    print(f"\n{i}. [{result['category'].upper()}] Score: {result['score']:.3f}")
                    print(f"   Source: {result['source']}.csv")
                    print(f"   Q: {result['question']}")
                    print(f"   A: {result['answer'][:100]}...")
            else:
                print("   No results found")
        except Exception as e:
            print(f"   Error: {e}")


if __name__ == "__main__":
    main()