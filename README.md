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
  *API endpoint exists for: External access, testing, or potential future client integrations*

### NL2SQL
- `POST /api/nl2sql/query` - Convert natural language to SQL
  ```json
  {
    "query": "string"
  }
  ```
  *API endpoint exists for: External access, testing, or potential future client integrations*

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

## System Architecture

```mermaid
graph TB
    subgraph "User Interface Layer"
        U[Hotel Guest/User]
        S[Streamlit Frontend<br/>pages/streamlit_app.py]
    end
    
    subgraph "API Gateway Layer"
        F[FastAPI Backend<br/>main.py]
        CA[Concierge API<br/>/api/concierge/ask]
        FA[FAQ API<br/>/api/faq/search]
        NA[NL2SQL API<br/>/api/nl2sql/query]
    end
    
    subgraph "Business Logic Layer"
        CAG[Concierge Agent<br/>concierge_agent.py]
        FS[FAQ Service<br/>search_service.py]
        NS[NL2SQL Service<br/>nl2sql_service.py]
    end
    
    subgraph "AI/ML Layer"
        OAI[OpenAI GPT-4o-mini<br/>Text Generation]
        EMB[OpenAI Embeddings<br/>text-embedding-3-small]
        LLAMA[LlamaIndex<br/>Vector Operations]
    end
    
    subgraph "Data Layer"
        PG[(PostgreSQL<br/>NeonDB<br/>guests, rooms, bookings)]
        R[(Redis<br/>Cache & Vectors<br/>FAQ embeddings)]
        CSV[CSV Files<br/>Raw data import]
    end
    
    subgraph "Infrastructure"
        VENV[Python Virtual Env<br/>.venv]
        DEPS[Dependencies<br/>requirements.txt]
        ENV[Environment Config<br/>.env]
    end
    
    U --> S
    S --> F
    F --> CA
    F --> FA
    F --> NA
    
    CA --> CAG
    FA --> FS
    NA --> NS
    
    CAG --> FS
    CAG --> NS
    CAG --> OAI
    FS --> EMB
    FS --> LLAMA
    NS --> PG
    
    F --> PG
    F --> R
    
    LLAMA --> R
    CSV --> PG
    
    VENV --> F
    VENV --> S
    DEPS --> VENV
    ENV --> F
```

## Agent Roles and Workflows

### AI Concierge Agent
**Role**: Primary conversational interface for hotel guests
**Workflow**:
1. Receives guest queries via `/api/concierge/ask`
2. Analyzes query intent (booking, dining, FAQ, general inquiry)
3. Routes to appropriate service or handles directly
4. Generates natural language responses using OpenAI GPT-4o-mini
5. Maintains conversation context per user session

### FAQ Search Agent
**Role**: Provides instant answers to common hotel questions
**Workflow**:
1. Receives search queries via `/api/faq/search`
2. Converts query to embeddings using OpenAI text-embedding-3-small
3. Performs vector similarity search in Redis
4. Returns most relevant FAQ answers
5. Falls back to general concierge if no matches found

### NL2SQL Agent
**Role**: Converts natural language questions to database queries
**Workflow**:
1. Receives natural language queries via `/api/nl2sql/query`
2. Analyzes query to understand data requirements
3. Generates appropriate SQL queries for PostgreSQL
4. Executes queries against hotel database
5. Formats results into natural language responses

### Workflow Integration
```
Guest Query → Streamlit UI → FastAPI → Agent Selection → AI Processing → Response
                                      ↓
                               Database/Redis Access
```

## Detailed Setup Instructions

### 1. Environment Setup

**Windows:**
```bash
python -m venv .venv
.venv\Scripts\activate
```

**macOS/Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

### 2. Database Configuration

1. Create a NeonDB PostgreSQL instance
2. Create tables:
   ```sql
   CREATE TABLE guests (
       id SERIAL PRIMARY KEY,
       name VARCHAR(255),
       email VARCHAR(255),
       phone VARCHAR(50)
   );
   
   CREATE TABLE rooms (
       id SERIAL PRIMARY KEY,
       room_number VARCHAR(10),
       room_type VARCHAR(50),
       capacity INT,
       price DECIMAL(10,2)
   );
   
   CREATE TABLE bookings (
       id SERIAL PRIMARY KEY,
       guest_id INT REFERENCES guests(id),
       room_id INT REFERENCES rooms(id),
       check_in DATE,
       check_out DATE,
       status VARCHAR(20)
   );
   ```

3. Import data using scripts in `scripts/` directory

### 3. Redis Setup

1. Install Redis server locally or use cloud Redis
2. Ensure Redis is running on default port 6379
3. Initialize vector store using `tests/integration/setup_vector_search.py`

### 4. OpenAI Configuration

1. Get API key from OpenAI platform
2. Add to `.env` file:
   ```
   OPENAI_API_KEY=your_actual_api_key_here
   ```

### 5. Vector Embeddings Setup

Run the vector search setup script:
```bash
python tests/integration/setup_vector_search.py
```

This will:
- Load FAQ data
- Generate embeddings
- Store in Redis vector database

## Configuration

### Environment Variables

Required environment variables in `.env`:
```env
DATABASE_URL=postgresql://user:password@host:port/database
REDIS_HOST=localhost
REDIS_PORT=6379
OPENAI_API_KEY=your_openai_api_key
```

### CORS Configuration

The FastAPI backend is configured with CORS to allow requests from the Streamlit frontend. Modify `backend/app/main.py` if you need different CORS settings.

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