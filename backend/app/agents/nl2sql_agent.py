"""Natural Language to SQL Agent using OpenAI/Ollama and database schema."""
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, inspect, text
from collections import defaultdict
from openai import ChatCompletion

# Add project root to path if not already there
try:
    from backend.app.config import get_settings
except ImportError:
    project_root = Path(__file__).parent.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    from backend.app.config import get_settings


class NL2SQLAgent:
    """Agent to convert natural language queries to SQL and execute them."""
    
    def __init__(self, model: str = "gpt-3.5-turbo", use_ollama: bool = False, fallback_to_ollama: bool = True):
        """
        Initialize the NL2SQL agent.
        
        Args:
            model: Model to use. For OpenAI: 'gpt-3.5-turbo', 'gpt-4o-mini', etc.
                   For Ollama: 'llama3', 'llama2', 'mistral', 'codellama', etc.
            use_ollama: If True, use Ollama instead of OpenAI
            fallback_to_ollama: If True, automatically fallback to Ollama if OpenAI fails
        """
        self.settings = get_settings()
        self.engine = create_engine(self.settings.database_url)
        self.model = model
        self.use_ollama = use_ollama
        self.fallback_to_ollama = fallback_to_ollama
        self.ollama_model = "llama3"  # Fallback model
        self.client = None
        self.ollama_url = "http://localhost:11434/api/generate"  # Initialize early
        self.ollama_available = False
        
        # Check if Ollama is available (if we might need it)
        if use_ollama or fallback_to_ollama:
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=2)
                self.ollama_available = (response.status_code == 200)
                if self.ollama_available:
                    print(f"✓ Ollama is available")
            except:
                self.ollama_available = False
                if use_ollama:
                    raise Exception(f"Ollama not available. Install from https://ollama.ai and run 'ollama pull {self.ollama_model}'")
        
        if not use_ollama:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.settings.openai_api_key)
                print(f"✓ Initialized with OpenAI model: {self.model}")
            except Exception as e:
                print(f"⚠ OpenAI initialization failed: {e}")
                if fallback_to_ollama and self.ollama_available:
                    print(f"→ Falling back to Ollama with {self.ollama_model}")
                    self.use_ollama = True
                elif fallback_to_ollama and not self.ollama_available:
                    raise Exception(f"OpenAI failed and Ollama not available. Install Ollama from https://ollama.ai and run 'ollama pull {self.ollama_model}'")
                else:
                    raise
        else:
            print(f"✓ Initialized with Ollama model: {self.model}")
        
        self.schema_info = self._get_schema_info()
    
    def _get_schema_info(self) -> str:
        """Get database schema information for context."""
        inspector = inspect(self.engine)
        schema_parts = []
        
        for table_name in inspector.get_table_names():
            columns = inspector.get_columns(table_name)
            col_info = ", ".join([f"{col['name']} ({col['type']})" for col in columns])
            schema_parts.append(f"Table: {table_name}\nColumns: {col_info}")
        
        return "\n\n".join(schema_parts)
    
    def _ensure_ollama_available(self):
        """Ensure Ollama is available before using it."""
        if not self.ollama_available:
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=2)
                self.ollama_available = (response.status_code == 200)
            except:
                self.ollama_available = False
        
        if not self.ollama_available:
            raise Exception(f"Ollama not available. Make sure Ollama is running and you have pulled the model with: ollama pull {self.ollama_model}")
    
    def _call_ollama(self, prompt: str, model: str = None) -> str:
        """Call Ollama API (local)."""
        import requests
        
        self._ensure_ollama_available()
        
        if model is None:
            model = self.model if self.use_ollama else self.ollama_model
        
        response = requests.post(
            self.ollama_url,
            json={
                "model": model,
                "prompt": prompt,
                "stream": False
            },
            timeout=120  # 2 minutes timeout for large responses
        )
        
        if response.status_code == 200:
            return response.json()["response"]
        else:
            raise Exception(f"Ollama error: {response.text}")
    
    #{self.schema_info}
    def generate_sql(self, natural_query: str) -> str:
        """
        Convert natural language query to SQL.
        
        Args:
            natural_query: Natural language question
            
        Returns:
            Generated SQL query
        """
        system_prompt = f"""You are an expert SQL query generator for a PostgreSQL database.
        
Database Schema:
{self.schema_info}

Your task is to convert natural language questions into valid PostgreSQL SQL queries.
IMPORTANT RULES:
- Return ONLY the SQL query, no explanations
- Use proper PostgreSQL syntax
- Handle joins when multiple tables are needed
- Use appropriate WHERE clauses, aggregations, and ORDER BY when needed
- Return SELECT queries only (no INSERT, UPDATE, DELETE)
- **ALWAYS use CASE-INSENSITIVE comparisons for text fields**:
  * Use ILIKE instead of LIKE for pattern matching
  * Use LOWER() function for exact text comparisons
  * Example: WHERE LOWER(column_name) = LOWER('value')
  * Example: WHERE column_name ILIKE '%value%'
- For status fields like 'Available', 'Occupied', etc., always use case-insensitive matching

Examples of case-insensitive queries:
- SELECT * FROM rooms WHERE LOWER(status) = LOWER('Available')
- SELECT * FROM rooms WHERE room_type ILIKE '%deluxe%'
- SELECT * FROM guests WHERE LOWER(name) ILIKE LOWER('%john%')
"""
        
        # Try OpenAI first if not using Ollama
        if not self.use_ollama and self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": natural_query}
                    ],
                    temperature=0.1
                )
                sql_query = response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠ OpenAI API error: {e}")
                if self.fallback_to_ollama and self.ollama_available:
                    print(f"→ Falling back to Ollama ({self.ollama_model})...")
                    full_prompt = f"{system_prompt}\n\nQuestion: {natural_query}\n\nSQL Query:"
                    sql_query = self._call_ollama(full_prompt, self.ollama_model).strip()
                else:
                    raise
        else:
            # Use Ollama
            full_prompt = f"{system_prompt}\n\nQuestion: {natural_query}\n\nSQL Query:"
            sql_query = self._call_ollama(full_prompt).strip()
        
        # Clean up the response (remove markdown code blocks if present)
        if sql_query.startswith("```sql"):
            sql_query = sql_query.replace("```sql", "").replace("```", "").strip()
        elif sql_query.startswith("```"):
            sql_query = sql_query.replace("```", "").strip()
        
        return sql_query
    
    def execute_query(self, sql_query: str) -> Dict[str, Any]:
        """
        Execute SQL query and return results.
        
        Args:
            sql_query: SQL query to execute
            
        Returns:
            Dict with columns and rows
        """
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql_query))
                columns = list(result.keys())
                rows = [dict(zip(columns, row)) for row in result.fetchall()]
                
                return {
                    "success": True,
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows)
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "columns": [],
                "rows": []
            }
    
    def query(self, natural_query: str) -> Dict[str, Any]:
        """
        Main method: Convert natural language to SQL and execute.
        
        Args:
            natural_query: Natural language question
            
        Returns:
            Dict with SQL query and results
        """
        # Generate SQL
        sql_query = self.generate_sql(natural_query)
        
        # Execute query
        result = self.execute_query(sql_query)
        
        return {
            "natural_query": natural_query,
            "sql_query": sql_query,
            **result
        }
    
    def explain_results(self, natural_query: str, results: Dict[str, Any]) -> str:
        """
        Generate natural language explanation of query results.
        
        Args:
            natural_query: Original natural language question
            results: Query results
            
        Returns:
            Natural language explanation
        """
        if not results.get("success"):
            return f"I encountered an error: {results.get('error')}"
        
        rows = results.get("rows", [])
        
        system_prompt = """You are a helpful assistant that explains database query results in natural language.
Be concise and clear. If there are many rows, summarize the key findings."""
        
        user_prompt = f"""Question: {natural_query}

Results ({len(rows)} rows):
{rows[:5]}  # Show first 5 rows

Explain these results in a clear, natural way."""
        
        # Try OpenAI first if not using Ollama
        if not self.use_ollama and self.client:
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.7
                )
                return response.choices[0].message.content.strip()
            except Exception as e:
                print(f"⚠ OpenAI API error: {e}")
                if self.fallback_to_ollama and self.ollama_available:
                    print(f"→ Falling back to Ollama ({self.ollama_model})...")
                    full_prompt = f"{system_prompt}\n\n{user_prompt}\n\nExplanation:"
                    return self._call_ollama(full_prompt, self.ollama_model).strip()
                else:
                    # Return simple explanation if fallback not available
                    return f"Found {len(rows)} results for the query."
        else:
            # Use Ollama
            full_prompt = f"{system_prompt}\n\n{user_prompt}\n\nExplanation:"
            return self._call_ollama(full_prompt).strip()


# For testing directly
if __name__ == "__main__":
    # This will try OpenAI first, then fallback to Ollama llama3 if it fails
    agent = NL2SQLAgent(model="gpt-3.5-turbo", use_ollama=False, fallback_to_ollama=True)
    
    # Test query
    # question = "How many tables are in the database?"
    # print(f"\nQuestion: {question}")
    
    # result = agent.query(question)
    # print(f"\nSQL: {result['sql_query']}")
    # print(f"Success: {result['success']}")
    # if result['success']:
    #     print(f"Results: {result['rows']}")