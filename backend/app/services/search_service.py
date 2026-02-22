"""Semantic search service using LlamaIndex and Redis vector store."""
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import pandas as pd

# Add project root to path first
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llama_index.core import Document, VectorStoreIndex, StorageContext, Settings
from llama_index.vector_stores.redis import RedisVectorStore
from llama_index.core.vector_stores import MetadataInfo, VectorStoreInfo

try:
    from backend.app.config import get_settings
except ImportError:
    from backend.app.config import get_settings


class HotelFAQSearchService:
    """Semantic search service for hotel FAQ using LlamaIndex + Redis + Ollama."""
    
    def __init__(self, redis_host: str = None, redis_port: int = None):
        """
        Initialize the search service.
        
        Args:
            redis_host: Redis server host
            redis_port: Redis server port
        """
        try:
            self.settings = get_settings()
        except Exception as e:
            raise Exception(f"Failed to load settings: {e}")
        
        # Redis connection
        self.redis_host = redis_host or self.settings.redis_host
        self.redis_port = redis_port or self.settings.redis_port
        self.redis_url = f"redis://{self.redis_host}:{self.redis_port}"

        # ------------------------------------------------------------------ #
        #  Configure Ollama for BOTH embeddings AND LLM queries               #
        # ------------------------------------------------------------------ #
        ollama_base_url  = getattr(self.settings, "ollama_base_url",  "http://localhost:11434")
        ollama_model     = getattr(self.settings, "ollama_model",     "llama3")
        ollama_embed_model = getattr(self.settings, "ollama_embed_model", "mxbai-embed-large")

        print(f"Initializing Ollama — LLM: {ollama_model}  Embed: {ollama_embed_model}  url: {ollama_base_url}")

        # 1. Embedding model (dedicated embedding model, NOT the generative LLM)
        try:
            from llama_index.embeddings.ollama import OllamaEmbedding
            self.embed_model = OllamaEmbedding(
                model_name=ollama_embed_model,  # ✅ mxbai-embed-large for better accuracy
                base_url=ollama_base_url,
            )
            # Verify connection and get actual dims
            test_embed = self.embed_model.get_text_embedding("test")
            self.embedding_dims = len(test_embed)
            print(f"[OK] Ollama embedding model ready  (dims={self.embedding_dims})")
        except Exception as e:
            raise Exception(
                f"Failed to initialize Ollama embedding model.\n"
                f"Make sure Ollama is running: ollama serve\n"
                f"And the model is pulled:     ollama pull {ollama_embed_model}\n"
                f"Error: {e}"
            )

        # 2. LLM (used for query synthesis / response generation)
        try:
            from llama_index.llms.ollama import Ollama
            self.llm = Ollama(
                model=ollama_model,
                base_url=ollama_base_url,
                request_timeout=300.0,
            )
            print(f"[OK] Ollama LLM ready")
        except Exception as e:
            raise Exception(
                f"Failed to initialize Ollama LLM.\n"
                f"Error: {e}"
            )

        # 3. Apply globally so ALL LlamaIndex operations use Ollama
        Settings.embed_model = self.embed_model
        Settings.llm         = self.llm
        Settings.chunk_size  = 512

        # Redis vector store
        self.vector_store = None
        self.index        = None
        self.query_engine = None
        
        print(f"[OK] FAQ Search Service initialized")
        print(f"  Redis : {self.redis_host}:{self.redis_port}")
        print(f"  LLM   : Ollama / {ollama_model}")
        print(f"  Embed : Ollama / {ollama_embed_model}  dims={self.embedding_dims}")

    # ---------------------------------------------------------------------- #
    #  Internal helpers                                                        #
    # ---------------------------------------------------------------------- #

    def _detect_content_columns(self, df: pd.DataFrame) -> tuple:
        """Auto-detect which columns contain the main content."""
        columns = df.columns.tolist()
        #in case more csv's are referred like amenities and services. The column names in those are also added below.
        question_patterns = ['question', 'query', 'title', 'q', 'prompt', 'input']
        answer_patterns   = ['answer', 'response', 'content', 'text', 'a', 'output', 'description']
        category_patterns = ['category', 'type', 'tag', 'class', 'label', 'group']
        
        primary_col  = None
        secondary_col = None
        category_col  = None
        
        for pattern in question_patterns:
            matches = [col for col in columns if pattern in col.lower()]
            if matches:
                primary_col = matches[0]
                break
        
        for pattern in answer_patterns:
            matches = [col for col in columns if pattern in col.lower()]
            if matches:
                secondary_col = matches[0]
                break
        
        for pattern in category_patterns:
            matches = [col for col in columns if pattern in col.lower()]
            if matches:
                category_col = matches[0]
                break
        
        if not primary_col and len(columns) > 0:
            primary_col = columns[0]
        if not secondary_col and len(columns) > 1:
            secondary_col = columns[1]
        elif not secondary_col:
            secondary_col = primary_col
        
        print(f"  Auto-detected columns:")
        print(f"    Primary (question): {primary_col}")
        print(f"    Secondary (answer): {secondary_col}")
        if category_col:
            print(f"    Category: {category_col}")
        
        return primary_col, secondary_col, category_col

    def _load_faq_from_csv(self, csv_files: List[str]) -> List[Document]:
        """Load FAQ data from CSV files (auto-detects column structure)."""
        documents   = []
        project_root = Path(__file__).parent.parent.parent.parent
        
        for csv_file in csv_files:
            try:
                csv_path = Path(csv_file) if Path(csv_file).is_absolute() else project_root / csv_file
                
                if not csv_path.exists():
                    print(f"[WARN] Warning: File not found: {csv_path}")
                    continue
                
                print(f"\nLoading data from: {csv_path.name}")
                df = pd.read_csv(csv_path)
                
                if df.empty:
                    print(f"[WARN] Warning: {csv_path.name} is empty")
                    continue
                
                print(f"  Found {len(df)} rows and {len(df.columns)} columns")
                print(f"  Columns: {list(df.columns)}")
                
                primary_col, secondary_col, category_col = self._detect_content_columns(df)
                
                for idx, row in df.iterrows():
                    try:
                        primary_text   = row.get(primary_col, "")
                        secondary_text = row.get(secondary_col, "")
                        
                        if pd.isna(primary_text) or str(primary_text).strip() == "":
                            continue
                        
                        if primary_col == secondary_col:
                            text = str(primary_text)
                        else:
                            if pd.isna(secondary_text) or str(secondary_text).strip() == "":
                                text = str(primary_text)
                            else:
                                text = f"{primary_col}: {primary_text}\n{secondary_col}: {secondary_text}"
                        
                        metadata = {
                            "source":  csv_path.stem,
                            "primary": str(primary_text),
                        }
                        
                        if primary_col != secondary_col and not pd.isna(secondary_text):
                            metadata["secondary"] = str(secondary_text)
                        
                        if category_col:
                            category_value = row.get(category_col, "general")
                            metadata["category"] = str(category_value) if not pd.isna(category_value) else "general"
                        else:
                            metadata["category"] = "general"
                        
                        for col in df.columns:
                            if col not in [primary_col, secondary_col, category_col]:
                                value = row.get(col)
                                if not pd.isna(value):
                                    metadata[col.lower().replace(' ', '_')] = str(value)
                        
                        documents.append(Document(text=text, metadata=metadata))
                        
                    except Exception as e:
                        print(f"[WARN] Warning: Error processing row {idx} in {csv_path.name}: {e}")
                        continue
                        
            except Exception as e:
                print(f"[WARN] Error loading {csv_file}: {e}")
                continue
        
        print(f"\n[OK] Loaded {len(documents)} documents from {len(csv_files)} CSV files")
        return documents

    def _load_faq_from_directory(self, data_dir: str = None) -> List[Document]:
        """Load all CSV files from a directory."""
        if data_dir is None:
            data_dir = self.settings.faq_data_dir
        
        if not data_dir:
            raise Exception("Data directory not configured. Set FAQ_DATA_DIR in .env")
        
        dir_path = Path(data_dir) if Path(data_dir).is_absolute() \
                   else Path(__file__).parent.parent.parent.parent / data_dir
        
        print(f"\nSearching for CSV files in: {dir_path}")
        
        if not dir_path.exists():
            raise Exception(f"Directory not found: {dir_path}")
        if not dir_path.is_dir():
            raise Exception(f"Not a directory: {dir_path}")
        
        csv_files = list(dir_path.glob("*.csv")) or list(dir_path.rglob("*.csv"))
        
        if not csv_files:
            raise Exception(f"No CSV files found in {dir_path}")
        
        print(f"Found {len(csv_files)} CSV files:")
        for f in csv_files:
            print(f"  - {f.name}")
        
        return self._load_faq_from_csv([str(f) for f in csv_files])

    # ---------------------------------------------------------------------- #
    #  Public API                                                              #
    # ---------------------------------------------------------------------- #

    def create_index(self, csv_files: List[str] = None, data_dir: str = None, index_name: str = "hotel_faq"):
        """Create and store vector index in Redis."""
        print(f"\n{'='*60}")
        print(f"Creating vector index: {index_name}")
        print(f"{'='*60}")
        
        documents = self._load_faq_from_csv(csv_files) if csv_files \
                    else self._load_faq_from_directory(data_dir)
        
        if not documents:
            raise Exception("No documents loaded.")
        
        try:
            from redisvl.schema import IndexSchema

            schema_dict = {
                "index": {
                    "name": "bluehorizon_index",
                    "prefix": "doc",
                    "storage_type": "hash"
                },
                "fields": [
                    {"name": "id",     "type": "tag"},
                    {"name": "doc_id", "type": "tag"},
                    {"name": "text",   "type": "text"},
                    {
                        "name": "vector",
                        "type": "vector",
                        "attrs": {
                            "algorithm":       "flat",
                            "dims":            self.embedding_dims,  # ✅ dynamically set from Ollama
                            "distance_metric": "cosine",
                            "datatype":        "float32"
                        }
                    }
                ]
            }

            schema = IndexSchema.from_dict(schema_dict)
            print(f"[OK] Schema created  (dims={self.embedding_dims})")

            self.vector_store = RedisVectorStore(
                schema=schema,
                redis_url=self.redis_url,
                overwrite=True,
            )
            print("[OK] RedisVectorStore created")

            storage_context = StorageContext.from_defaults(vector_store=self.vector_store)

            print("\nCreating embeddings and storing in Redis (this may take a while)...")
            self.index = VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context,
                show_progress=True
            )

            self.query_engine = self.index.as_query_engine(similarity_top_k=5)
            print(f"\n[OK] Index created with {len(documents)} documents")

        except Exception as e:
            import traceback
            traceback.print_exc()
            raise

        return self.index

    def load_index(self, index_name: str = "hotel_faq"):
        """Load existing index from Redis."""
        print(f"Loading existing index: {index_name}")
        
        try:
            self.vector_store = RedisVectorStore(redis_url=self.redis_url)
        except Exception as e:
            raise Exception(f"Failed to connect to Redis: {e}")
        
        try:
            self.index = VectorStoreIndex.from_vector_store(self.vector_store)
        except Exception as e:
            raise Exception(f"Failed to load index. Run create_index() first. Error: {e}")
        
        self.query_engine = self.index.as_query_engine(similarity_top_k=5)
        print("[OK] Index loaded successfully")

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """Perform semantic search using Ollama for both embedding and response."""
        if not self.index:
            raise Exception("Index not loaded. Call create_index() or load_index() first.")
        
        print(f"\n🔍 Searching for: '{query}'")
        
        # ✅ Ollama is used here via Settings.embed_model (for query embedding)
        #    and Settings.llm (for response synthesis)
        self.query_engine = self.index.as_query_engine(similarity_top_k=top_k)
        response = self.query_engine.query(query)
        
        results = []
        for node in response.source_nodes:
            result = {
                "question":  node.metadata.get("primary", node.text[:200]),
                "category":  node.metadata.get("category", "general"),
                "source":    node.metadata.get("source", "unknown"),
                "score":     float(node.score) if node.score else 0.0,
                "relevance": (
                    "High"   if node.score and node.score > 0.8 else
                    "Medium" if node.score and node.score > 0.6 else
                    "Low"
                )
            }
            
            if "secondary" in node.metadata:
                result["answer"] = node.metadata["secondary"]
            
            for key, value in node.metadata.items():
                if key not in ["primary", "secondary", "source", "category"]:
                    result[key] = value
            
            results.append(result)
        
        return results

    def search_by_category(self, query: str, category: str, top_k: int = 3) -> List[Dict[str, Any]]:
        """Search within a specific category."""
        all_results = self.search(query, top_k=10)
        filtered = [r for r in all_results if r["category"].lower() == category.lower()]
        return filtered[:top_k]


# --------------------------------------------------------------------------- #
#  Singleton                                                                   #
# --------------------------------------------------------------------------- #

_search_service: Optional[HotelFAQSearchService] = None

def get_search_service() -> HotelFAQSearchService:
    """Get or create search service instance."""
    global _search_service
    if _search_service is None:
        _search_service = HotelFAQSearchService()
    return _search_service
