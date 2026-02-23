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
    index_name = HotelFAQSearchService.INDEX_NAME
    print(f"Vector Index Name: {index_name}")
    
    # Auto-discover all CSV files in the FAQ directory
    print(f"\nAuto-discovering CSV files from: {faq_dir}")
    search_service.create_index(
        data_dir=faq_dir,
        index_name=index_name,
    )
    
    print("\n" + "=" * 60)
    print("✓ Vector search setup complete!")
    print("=" * 60)
    
    # Test search across all knowledge bases
    print("\n" + "=" * 60)
    print("Testing Search — FAQ / Amenities / Services")
    print("=" * 60)

    test_queries = [
        ("What is the cancellation policy?",             None),
        # ("What time can I check in?",                    None),
        # ("Do you have a spa? What massages are offered?","amenities"),
        # ("Is breakfast included?",                       "faq"),
        # ("What room service options are available?",     "services"),
    ]

    for query, category in test_queries:
        print(f"\n  Query : '{query}'")
        if category:
            print(f"  Filter: category='{category}'")
        print("-" * 60)
        try:
            if category:
                results = search_service.search_by_category(query, category=category, top_k=3)
            else:
                results = search_service.search(query, top_k=10)

            if results:
                for i, result in enumerate(results, 1):
                    print(f"  {i}. [{result['doc_type'].upper()} / {result['category']}]  "
                          f"score={result['score']:.3f}  relevance={result['relevance']}")
                    print(f"     Q: {result['question'][:80]}")
                    ans = result.get('answer', '')
                    if ans:
                        print(f"     A: {ans[:100]}...")

                # Generate a synthesised answer from the top results
                explanation = search_service.explain_results(query, results)
                print(f"\n  [OpenAI Answer] {explanation}")
            else:
                print("  No results found")
        except Exception as e:
            print(f"  Error: {e}")


if __name__ == "__main__":
    main()