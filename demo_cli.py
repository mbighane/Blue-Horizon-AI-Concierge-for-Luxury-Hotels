"""
CLI Demo Script - Simulates user interaction with the Blue Horizon CLI
"""
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(__file__))

from backend.run_concierge import run_concierge_interaction

def demo_cli():
    """Demonstrate CLI functionality with simulated inputs"""
    print("=" * 60)
    print("Blue Horizon AI Concierge CLI - Demo Mode")
    print("=" * 60)
    print()
    
    # Simulated user inputs
    demo_inputs = [
        "Hello",
        "I want to book a luxury room for 2 nights",
        "Tell me about your dining options",
        "I need a relaxing spa treatment",
        "help",
    ]
    
    for user_input in demo_inputs:
        print(f"You: {user_input}")
        response = run_concierge_interaction(user_input)
        print(f"Concierge: {response}")
        print()
    
    print("Demo completed! To use the interactive CLI, run:")
    print("  python scripts/cli.py")
    print()
    print("Or from within the scripts directory:")
    print("  cd scripts && python cli.py")

if __name__ == "__main__":
    demo_cli()
