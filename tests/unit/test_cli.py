"""
Test script for CLI functionality
"""
import sys
import os

# Add project root to path
#sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root))
from scripts.run_concierge import run_concierge_interaction

def test_run_concierge():
    """Test run_concierge with various inputs"""
    print("=" * 60)
    print("Testing run_concierge.py module")
    print("=" * 60)
    
    test_cases = [
        "Hello",
        "I need to book a room for tonight",
        "What restaurants do you have?",
        "I'd like a spa treatment",
        "Can you help me?",
        "What's the weather like?"
    ]
    
    for i, test_input in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_input}")
        response = run_concierge_interaction(test_input)
        print(f"Response: {response}")
    
    print("\n" + "=" * 60)
    print("✓ All tests completed successfully!")
    print("=" * 60)

if __name__ == "__main__":
    test_run_concierge()
