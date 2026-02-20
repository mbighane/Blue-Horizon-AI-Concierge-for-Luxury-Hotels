# cli.py
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.run_concierge import run_concierge_interaction

def main():
    print("Welcome to the Blue Horizon AI Concierge CLI")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ")
        if user_input.lower() in ['exit', 'quit']:
            print("Goodbye!")
            break

        response = run_concierge_interaction(user_input)
        print(f"Concierge: {response}")

if __name__ == "__main__":
    main()