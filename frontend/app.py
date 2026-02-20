import streamlit as st
import requests
import uuid
import random

# Streamlit app title
st.title("Blue Horizon Chat Interface")

# Generate a unique user ID for the session
if "user_id" not in st.session_state:
    st.session_state["user_id"] = str(uuid.uuid4())

# Display the generated user ID (optional, for debugging)
st.text(f"Session User ID: {st.session_state['user_id']}")

# Input field for the message
message = st.text_area("Message", placeholder="Type your message here")

# Button to send the message
if st.button("Send Message"):
    if message:
        # Send the message to the FastAPI backend
        response = requests.post(
            "http://localhost:8000/api/chat/agent",
            json={"user_id": st.session_state["user_id"], "message": message}
        )

        if response.status_code == 200:
            st.success("Response:")
            st.write(response.json().get("response", "No response received"))
        else:
            st.error("Error:")
            st.write(response.json().get("error", "Unknown error occurred"))
    else:
        st.warning("Please provide a message.")

# Function to simulate multiple guest conversations
def simulate_guest_conversations():
    guest_ids = [str(uuid.uuid4()) for _ in range(5)]  # Generate 5 unique guest IDs
    sample_messages = [
        "What are the check-in timings?",
        "Can you recommend some nearby restaurants?",
        "What is the Wi-Fi password?",
        "Are there any spa services available?",
        "Can I get a late checkout?"
    ]

    st.header("Simulated Guest Conversations")

    for guest_id in guest_ids:
        st.subheader(f"Guest ID: {guest_id}")
        for message in random.sample(sample_messages, 3):  # Each guest sends 3 random messages
            response = requests.post(
                "http://localhost:8000/api/chat/agent",
                json={"user_id": guest_id, "message": message}
            )

            if response.status_code == 200:
                st.write(f"Message: {message}")
                st.success(f"Response: {response.json().get('response', 'No response received')}")
            else:
                st.write(f"Message: {message}")
                st.error(f"Error: {response.json().get('error', 'Unknown error occurred')}")

# Button to trigger simulation
if st.button("Simulate Guest Conversations"):
    simulate_guest_conversations()