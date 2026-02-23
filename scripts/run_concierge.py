# run_concierge.py
"""
Core concierge interaction handler for Blue Horizon.
This module provides a simple interface for CLI and API to interact with the AI.
"""

def run_concierge_interaction(user_input: str) -> str:
    """
    Takes user input and returns a response from the concierge.
    This is the core of the agent loop used in CLI and API.

    Args:
        user_input: The user's query or request

    Returns:
        str: Response from the concierge system
    """
    try:
        # For now, provide a simple mock response
        # TODO: Integrate with actual AI orchestrator/chat service

        user_input_lower = user_input.lower()

        if "book" in user_input_lower or "room" in user_input_lower:
            return "I'd be happy to help you book a room! Please tell me your preferred dates and room type."
        elif "restaurant" in user_input_lower or "dining" in user_input_lower:
            return "Our hotel features three exquisite restaurants. Would you like to make a reservation?"
        elif "spa" in user_input_lower or "massage" in user_input_lower:
            return "Our luxury spa offers a variety of treatments. What type of service interests you?"
        elif "hello" in user_input_lower or "hi" in user_input_lower:
            return "Hello! Welcome to Blue Horizon. How may I assist you today?"
        elif "help" in user_input_lower:
            return "I can help you with room bookings, dining reservations, spa appointments, local recommendations, and more. What would you like to know?"
        else:
            return f"Thank you for your inquiry: '{user_input}'. I'm here to help with all your hospitality needs. Could you please provide more details?"

    except Exception as e:
        return f"[Error]: {str(e)}"


# Test/Debug block
if __name__ == "__main__":
    # Add a breakpoint on the line below, then press F5
    print("Testing run_concierge_interaction...")

    # Test with different inputs
    test_inputs = ["Hello", "I need a room", "help"]

    for user_input in test_inputs:
        print(f"\nInput: {user_input}")
        response = run_concierge_interaction(user_input)
        print(f"Response: {response}")
