from collections import defaultdict
from openai import OpenAI

class OpenAIChatAgent:
    """Chat agent with session memory and context tracking."""

    def __init__(self, settings):
        self.sessions = defaultdict(list)  # Store session history per user
        self.settings = settings  # Assign settings to the instance

    def process_message(self, user_id: str, message: str) -> str:
        """Process a user message with context tracking."""
        # Retrieve session history
        session_history = self.sessions[user_id]

        # Append the new message to the session history
        session_history.append({"role": "user", "content": message})

        # Generate a response using OpenAI
        response = self._generate_response(session_history)

        # Append the response to the session history
        session_history.append({"role": "assistant", "content": response})

        return response

    def _generate_response(self, session_history: list) -> str:
        """Generate a response using OpenAI API."""
        try:
            import openai  # Ensure the OpenAI library is imported

            openai.api_key = self.settings.openai_api_key  # Set the API key
            completion = openai.ChatCompletion.create(
                model=self.settings.openai_model,
                messages=session_history
            )
            return completion.choices[0].message["content"]
        except Exception as e:
            return f"Error generating response: {str(e)}"