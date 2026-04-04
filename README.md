# Blue Horizon - AI-Powered Hospitality Concierge

An intelligent concierge system for luxury hotels, featuring AI-powered guest assistance, FAQ search, and natural language database queries.

## Features

- 🤖 **AI Concierge Agent**: Intelligent conversation handling for guest inquiries
- 🔍 **FAQ Search**: Vector-based search through hotel FAQs using embeddings
- 📊 **NL2SQL Queries**: Natural language to SQL conversion for database queries
- 💬 **Multi-user Support**: Session-based conversations with unique user IDs
- 🎯 **Hospitality Focus**: Specialized for hotel operations (bookings, dining, spa, etc.)
- 🔄 **Real-time Responses**: FastAPI backend with async processing

## Tech Stack

- **Backend**: FastAPI, Python
- **Frontend**: Streamlit
- **Database**: PostgreSQL (NeonDB)
- **Cache/Vector Store**: Redis
- **AI**: OpenAI GPT-4o-mini, OpenAI Embeddings
- **Vector Search**: Redis with LlamaIndex

## Prerequisites

- Python 3.8+
- PostgreSQL database (NeonDB recommended)
- Redis instance
- OpenAI API key

## Installation

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd BlueHorizon
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv .venv
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**:
   Create a `.env` file in the root directory:
   ```env
   DATABASE_URL=postgresql://user:password@host:port/database
   REDIS_HOST=localhost
   REDIS_PORT=6379
   OPENAI_API_KEY=your_openai_api_key
   ```

## Running the Application

### Backend (FastAPI)

1. Activate the virtual environment (if not already activated):
   ```bash
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. Start the FastAPI server:
   ```bash
   uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
   ```

The API will be available at: http://localhost:8000

API Documentation: http://localhost:8000/docs

### Frontend (Streamlit)

1. In a new terminal, activate the virtual environment:
   ```bash
   # Windows:
   .venv\Scripts\activate
   # macOS/Linux:
   source .venv/bin/activate
   ```

2. Start the Streamlit app:
   ```bash
   streamlit run frontend/pages/streamlit_app.py 
   ```

The web interface will be available at: http://localhost:8501

## API Endpoints

### Concierge Agent
- `POST /api/concierge/ask` - Main AI concierge endpoint
  ```json
  {
    "user_id": "string",
    "message": "string"
  }
  ```

### FAQ Search
- `POST /api/faq/search` - Search hotel FAQs
  ```json
  {
    "query": "string"
  }
  ```

### NL2SQL
- `POST /api/nl2sql/query` - Convert natural language to SQL
  ```json
  {
    "query": "string"
  }
  ```

## Project Structure

```
BlueHorizon/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI application entry point
│   │   ├── config.py            # Application configuration
│   │   ├── api/                 # API route handlers
│   │   │   ├── concierge.py     # Concierge endpoints
│   │   │   ├── faq.py          # FAQ endpoints
│   │   │   └── nl2sql.py       # NL2SQL endpoints
│   │   ├── agents/             # AI agent implementations
│   │   ├── models/             # Database models
│   │   ├── schemas/            # Pydantic schemas
│   │   ├── services/           # Business logic services
│   │   └── utils/              # Utility functions
├── frontend/
│   ├── app.py                  # Main Streamlit application
│   ├── pages/                  # Additional Streamlit pages
│   ├── components/             # Reusable UI components
│   └── utils/                  # Frontend utilities
├── data/                       # Data files and embeddings
├── scripts/                    # Utility scripts
├── tests/                      # Test suites
├── requirements.txt            # Python dependencies
└── .env                        # Environment variables
```

## Configuration

### Database Setup

The application expects a PostgreSQL database with the following tables:
- `guests` - Guest information
- `rooms` - Room details
- `bookings` - Reservation data

Use the scripts in `scripts/` to import CSV data.

### Vector Search Setup

FAQ search requires vector embeddings stored in Redis. Run the setup scripts in `tests/integration/` to initialize the vector store.

## Development

### Running Tests

```bash
pytest
```

### Code Quality

```bash
# Linting and formatting (add your preferred tools)
```

## Usage Examples

### Basic Conversation
1. Start both backend and frontend
2. In the web interface, enter: "What time is check-in?"
3. The AI concierge will respond with hotel policies

### FAQ Search
The system automatically searches relevant FAQs based on guest queries.

### Database Queries
Ask questions like: "How many rooms are available next week?"

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- Built with FastAPI, Streamlit, and OpenAI
- Vector search powered by Redis and LlamaIndex
- Database hosted on NeonDB</content>
<parameter name="filePath">d:\Manisha\IKCapStoneProject\BlueHorizon\README.md