"""Natural Language to SQL service using OpenAI/Ollama."""
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List
from sqlalchemy import create_engine, text
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


class NL2SQLService:
    """Service to convert natural language queries to SQL and execute them."""
    
    def __init__(self, model: str = "gpt-4o-mini", use_ollama: bool = False, fallback_to_ollama: bool = True):
        """
        Initialize the NL2SQL agent.
        
        Args:
            model: Model to use. For OpenAI: 'gpt-3.5-turbo', 'gpt-4o-mini', etc.
                   For Ollama: 'llama3', 'llama2', 'mistral', 'codellama', etc.
            use_ollama: If True, use Ollama instead of OpenAI
            fallback_to_ollama: If True, automatically fallback to Ollama if OpenAI fails
        """
        self.settings = get_settings()
        self.engine = create_engine(
            self.settings.database_url,
            pool_pre_ping=True,       # test connection before using it
            pool_recycle=300,         # recycle connections every 5 minutes
            pool_size=5,
            max_overflow=10,
            connect_args={"connect_timeout": 50, "keepalives": 1,
                          "keepalives_idle": 30, "keepalives_interval": 10,
                          "keepalives_count": 5},
        )
        self.model = model
        self.use_ollama = use_ollama
        self.fallback_to_ollama = fallback_to_ollama
        self.ollama_model = "codellama"  # Fallback model
        self.client = None
        self.ollama_url = "http://localhost:11434/api/generate"  # Initialize early
        self.ollama_available = False
        
        # Check if Ollama is available (if we might need it)
        if use_ollama or fallback_to_ollama:
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=300)
                self.ollama_available = (response.status_code == 200)
                if self.ollama_available:
                    print(f"[OK] Ollama is available")
            except:
                self.ollama_available = False
                if use_ollama:
                    raise Exception(f"Ollama not available. Install from https://ollama.ai and run 'ollama pull {self.ollama_model}'")
        
        if not use_ollama:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.settings.openai_api_key)
                print(f"[OK] Initialized with OpenAI model: {self.model}")
            except Exception as e:
                print(f"[WARN] OpenAI initialization failed: {e}")
                if fallback_to_ollama and self.ollama_available:
                    print(f"-> Falling back to Ollama with {self.ollama_model}")
                    self.use_ollama = True
                elif fallback_to_ollama and not self.ollama_available:
                    raise Exception(f"OpenAI failed and Ollama not available. Install Ollama from https://ollama.ai and run 'ollama pull {self.ollama_model}'")
                else:
                    raise
        else:
            print(f"[OK] Initialized with Ollama model: {self.model}")
        
    def _ensure_ollama_available(self):
        """Ensure Ollama is available before using it."""
        if not self.ollama_available:
            try:
                import requests
                response = requests.get("http://localhost:11434/api/tags", timeout=300)
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
            model = self.model if not self.use_ollama else self.ollama_model
        
        response = requests.post(
            self.ollama_url,
            json={
                "model": "codellama",
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": 0.1,      # Low temp for deterministic SQL
                    "num_predict": 256,      # Limit output tokens - SQL is short
                    "num_ctx": 2048          # Limit context window for speed
                }
            },
            timeout=300  # 5 minutes - codellama is a large model
        )
        
        if response.status_code == 200:
            try:
                data = response.json()
                return data.get("response") or data.get("message") or str(data)
            except Exception:
                raise Exception(
                    f"Ollama returned a non-JSON body (status 200): {response.text!r}"
                )
        else:
            raise Exception(f"Ollama error {response.status_code}: {response.text}")
    
    def generate_sql(self, natural_query: str) -> str:
        """
        Convert natural language query to SQL.
        
        Args:
            natural_query: Natural language question
            
        Returns:
            Generated SQL query
        """
        system_prompt = """You are a PostgreSQL SQL expert. Generate ONLY a valid SQL SELECT query.

Rules:
- Return ONLY the SQL query, no explanations or markdown
- PostgreSQL syntax only
- SELECT queries only
- Use ILIKE for text matching (case-insensitive)
- Use LOWER() for exact text comparisons
- Never use DISTINCT ON together with GROUP BY — use one or the other
- Never select customer_id as a raw value; always JOIN with the customers table and return the customer's full name as (customers.first_name || ' ' || customers.last_name) AS customer_name
- If a query involves any table with a customer_id foreign key, JOIN customers ON customer.id = <table>.customer_id and expose customer_name instead
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
                print(f"[WARN] OpenAI API error: {e}")
                if self.fallback_to_ollama and self.ollama_available:
                    print(f"-> Falling back to Ollama ({self.ollama_model})...")
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
        last_error = None
        for attempt in range(2):  # retry once on SSL/connection errors
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
                last_error = e
                err_str = str(e).lower()
                if attempt == 0 and ("ssl" in err_str or "connection" in err_str or "closed" in err_str):
                    print(f"[NL2SQL] Connection error on attempt {attempt + 1}, retrying: {e}")
                    self.engine.dispose()  # force new connections on retry
                    continue
                break
        return {
            "success": False,
            "error": str(last_error),
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
                print(f"[WARN] OpenAI API error: {e}")
                if self.fallback_to_ollama and self.ollama_available:
                    print(f"-> Falling back to Ollama ({self.ollama_model})...")
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
    agent = NL2SQLService(model="gpt-4o-mini", use_ollama=False, fallback_to_ollama=True)
    
    # Test query
    # question = "How many tables are in the database?"
    # print(f"\nQuestion: {question}")
    
    # result = agent.query(question)
    # print(f"\nSQL: {result['sql_query']}")
    # print(f"Success: {result['success']}")
    # if result['success']:
    #     print(f"Results: {result['rows']}")