"""
Semantic Search Service - Blue Horizon Hotel
Uses LlamaIndex + Redis vector store + OpenAI embeddings/LLM.

Supported knowledge bases (loaded from FAQData directory):
  - faq_knowledge_base.csv  : hotel policy, check-in/out, booking, cancellation
  - amenities.csv           : spa, pool, gym and other amenity details
  - services.csv            : concierge, room service, department services

Public API:
    service = HotelFAQSearchService()
    service.create_index(data_dir='.../FAQData')  # build + persist to Redis
    service.load_index()                          # reload from existing Redis index
    results = service.search('cancellation policy', top_k=5)
    results = service.search_by_category('spa hours', category='amenities', top_k=3)
    answer  = service.explain_results('Do you have a spa?', results)
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from openai import OpenAI

project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from llama_index.core import Document, Settings, StorageContext, VectorStoreIndex
from llama_index.vector_stores.redis import RedisVectorStore

try:
    from backend.app.config import get_settings
except ImportError:
    from backend.app.config import get_settings


# ---------------------------------------------------------------------------
# Per-CSV column mappings
# Each entry: text_cols, category_col, meta_cols, label
#   text_cols    - ordered columns whose values form the document text
#   category_col - column used for metadata["category"]
#   meta_cols    - additional columns kept in metadata
# ---------------------------------------------------------------------------
_CSV_SCHEMAS: Dict[str, Dict] = {
    "faq_knowledge_base": {
        "text_cols":    ["question", "answer"],
        "category_col": "category",
        "meta_cols":    ["subcategory", "keywords", "helpful_votes"],
        "label":        "faq",
    },
    "amenities": {
        "text_cols":    ["name", "description"],
        "category_col": "category",
        "meta_cols":    ["price", "duration", "availability", "location", "booking_required"],
        "label":        "amenities",
    },
    "services": {
        "text_cols":    ["name", "description"],
        "category_col": "service_type",
        "meta_cols":    ["duration_minutes", "price", "department", "booking_required"],
        "label":        "services",
    },
}

# ---------------------------------------------------------------------------
# System prompt for FAQ answer synthesis
# ---------------------------------------------------------------------------
_FAQ_EXPLAIN_SYSTEM_PROMPT = """You are a knowledgeable and warm concierge at Blue Horizon, a luxury hotel.
A guest has asked a question and the knowledge base has returned relevant matches.
Using ONLY the provided source excerpts, compose a clear, friendly, helpful answer.
Rules:
- Answer in 2-5 sentences. Be concise but complete.
- If multiple sources are relevant, synthesize them into one coherent answer.
- If no source is relevant enough (all scores < 0.4), politely say you don't have that
  information and suggest the guest contact the front desk.
- Never invent details not present in the sources.
- Format prices, times, and durations naturally (e.g. '$120 for 60 minutes')."""

_QUESTION_PATTERNS = ["question", "query", "title", "prompt", "input", "q"]
_ANSWER_PATTERNS   = ["answer", "response", "content", "text", "output", "description", "a"]
_CATEGORY_PATTERNS = ["category", "type", "tag", "class", "label", "group", "service_type"]


# ---------------------------------------------------------------------------
# Document builders
# ---------------------------------------------------------------------------

def _build_documents_known(df: pd.DataFrame, stem: str) -> List[Document]:
    """Build documents for a CSV whose schema is in _CSV_SCHEMAS."""
    schema       = _CSV_SCHEMAS[stem]
    text_cols    = [c for c in schema["text_cols"]    if c in df.columns]
    category_col = schema["category_col"] if schema["category_col"] in df.columns else None
    meta_cols    = [c for c in schema["meta_cols"]    if c in df.columns]
    label        = schema["label"]

    documents: List[Document] = []
    for _, row in df.iterrows():
        parts = []
        for col in text_cols:
            val = row.get(col, "")
            if pd.notna(val) and str(val).strip():
                parts.append(f"{col}: {val}")
        if not parts:
            continue

        text = "\n".join(parts)
        metadata: Dict[str, Any] = {
            "source":   stem,
            "doc_type": label,
            "category": (
                str(row[category_col]).strip()
                if category_col and pd.notna(row[category_col])
                else label
            ),
        }
        if text_cols:
            metadata["primary"] = str(row.get(text_cols[0], "")).strip()
        if len(text_cols) > 1:
            metadata["answer"]  = str(row.get(text_cols[1], "")).strip()

        for col in meta_cols:
            val = row.get(col)
            if pd.notna(val):
                metadata[col] = str(val).strip()

        documents.append(Document(text=text, metadata=metadata))
    return documents


def _build_documents_generic(df: pd.DataFrame, stem: str) -> List[Document]:
    """Fallback builder for CSVs not listed in _CSV_SCHEMAS."""
    cols      = df.columns.tolist()
    lower_col = {c.lower(): c for c in cols}

    primary_col   = next((lower_col[p] for p in _QUESTION_PATTERNS  if p in lower_col), cols[0] if cols else None)
    secondary_col = next((lower_col[p] for p in _ANSWER_PATTERNS    if p in lower_col), cols[1] if len(cols) > 1 else primary_col)
    category_col  = next((lower_col[p] for p in _CATEGORY_PATTERNS  if p in lower_col), None)

    documents: List[Document] = []
    for _, row in df.iterrows():
        primary   = str(row.get(primary_col,   "")).strip() if primary_col   else ""
        secondary = str(row.get(secondary_col, "")).strip() if secondary_col else ""
        if not primary:
            continue

        text = primary if primary == secondary else f"{primary_col}: {primary}\n{secondary_col}: {secondary}"
        metadata: Dict[str, Any] = {
            "source":   stem,
            "doc_type": "faq",
            "primary":  primary,
            "answer":   secondary,
            "category": (
                str(row[category_col]).strip()
                if category_col and pd.notna(row[category_col])
                else "general"
            ),
        }
        documents.append(Document(text=text, metadata=metadata))
    return documents


# ---------------------------------------------------------------------------
# Service class
# ---------------------------------------------------------------------------

class HotelFAQSearchService:
    """
    Semantic search over hotel FAQ, amenities, and services knowledge bases.

    Embedding : OpenAI text-embedding-3-small  (dims=1536)
    LLM       : OpenAI gpt-4o-mini
    Vector DB : Redis via LlamaIndex RedisVectorStore
    """

    INDEX_NAME = "bluehorizon_faq"

    def __init__(
        self,
        redis_host: Optional[str] = None,
        redis_port: Optional[int] = None,
    ) -> None:
        try:
            self.settings = get_settings()
        except Exception as exc:
            raise RuntimeError(f"Failed to load settings: {exc}") from exc

        self.redis_host = redis_host or self.settings.redis_host
        self.redis_port = redis_port or self.settings.redis_port
        self.redis_url  = f"redis://{self.redis_host}:{self.redis_port}"

        openai_key   = self.settings.openai_api_key
        openai_model = self.settings.openai_model
        openai_embed = getattr(self.settings, "openai_text_embedding_model", "text-embedding-3-small")

        print(f"[SearchService] LLM={openai_model}  Embed={openai_embed}")

        # Embedding model
        try:
            from llama_index.embeddings.openai import OpenAIEmbedding
            self._embed_model = OpenAIEmbedding(
                model=openai_embed,
                api_key=openai_key,
                embed_batch_size=100,
            )
            probe = self._embed_model.get_text_embedding("test")
            self.embedding_dims = len(probe)
            print(f"[OK] Embedding model ready  dims={self.embedding_dims}")
        except Exception as exc:
            raise RuntimeError(
                f"OpenAI embedding init failed - check OPENAI_API_KEY.\n{exc}"
            ) from exc

        # LLM
        try:
            from llama_index.llms.openai import OpenAI as LlamaOpenAI
            self._llm = LlamaOpenAI(
                model=openai_model,
                api_key=openai_key,
                request_timeout=120.0,
            )
            print(f"[OK] LLM ready  model={openai_model}")
        except Exception as exc:
            raise RuntimeError(f"OpenAI LLM init failed.\n{exc}") from exc

        Settings.embed_model = self._embed_model
        Settings.llm         = self._llm
        Settings.chunk_size  = 512

        # Direct OpenAI client for explain_results (bypasses LlamaIndex)
        self._openai_client = OpenAI(api_key=openai_key)
        self.model          = openai_model

        self._vector_store: Optional[RedisVectorStore] = None
        self._index:        Optional[VectorStoreIndex] = None

        print(f"[OK] SearchService ready  redis={self.redis_host}:{self.redis_port}")

    # -------------------------------------------------------------------------
    # Document loading
    # -------------------------------------------------------------------------

    def _load_csv(self, csv_path: Path) -> List[Document]:
        """Load a single CSV file into LlamaIndex Documents."""
        stem = csv_path.stem.lower()
        print(f"  Loading {csv_path.name} ... ", end="", flush=True)
        df = pd.read_csv(csv_path)
        if df.empty:
            print("(empty - skipped)")
            return []
        df.columns = [c.strip() for c in df.columns]
        builder = _build_documents_known if stem in _CSV_SCHEMAS else _build_documents_generic
        docs    = builder(df, stem)
        print(f"{len(docs)} documents")
        return docs

    def _load_directory(self, data_dir: str) -> List[Document]:
        """Discover and load all CSV files from data_dir."""
        dir_path = Path(data_dir)
        if not dir_path.is_dir():
            raise FileNotFoundError(f"FAQ data directory not found: {dir_path}")

        csv_files = sorted(dir_path.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(f"No CSV files found in {dir_path}")

        print(f"\nFound {len(csv_files)} CSV file(s) in {dir_path.name}/")
        all_docs: List[Document] = []
        for path in csv_files:
            all_docs.extend(self._load_csv(path))

        print(f"[OK] Total documents loaded: {len(all_docs)}")
        return all_docs

    # -------------------------------------------------------------------------
    # Index management
    # -------------------------------------------------------------------------

    def create_index(
        self,
        csv_files:  Optional[List[str]] = None,
        data_dir:   Optional[str]       = None,
        index_name: str                 = INDEX_NAME,
    ) -> VectorStoreIndex:
        """
        Build a fresh vector index from CSV files and persist to Redis.

        Args:
            csv_files  : explicit list of CSV paths (takes priority over data_dir).
            data_dir   : directory to auto-discover all CSVs from.
            index_name : Redis index name / key prefix.

        Returns:
            The created VectorStoreIndex.
        """
        print(f"\n{'='*60}")
        print(f" Building vector index  [{index_name}]")
        print(f"{'='*60}")

        if csv_files:
            documents = []
            for f in csv_files:
                documents.extend(self._load_csv(Path(f)))
        else:
            target_dir = data_dir or self.settings.faq_data_dir
            documents  = self._load_directory(target_dir)

        if not documents:
            raise RuntimeError("No documents loaded - check CSV paths.")

        from redisvl.schema import IndexSchema
        schema = IndexSchema.from_dict({
            "index": {
                "name":         index_name,
                "prefix":       "doc",
                "storage_type": "hash",
            },
            "fields": [
                {"name": "id",     "type": "tag"},
                {"name": "doc_id", "type": "tag"},
                {"name": "text",   "type": "text"},
                {
                    "name":  "vector",
                    "type":  "vector",
                    "attrs": {
                        "algorithm":       "flat",
                        "dims":            self.embedding_dims,
                        "distance_metric": "cosine",
                        "datatype":        "float32",
                    },
                },
            ],
        })

        self._vector_store = RedisVectorStore(
            schema=schema,
            redis_url=self.redis_url,
            overwrite=True,
        )
        print(f"[OK] RedisVectorStore ready  (dims={self.embedding_dims}, overwrite=True)")

        storage_context = StorageContext.from_defaults(vector_store=self._vector_store)
        print(f"\nEmbedding {len(documents)} documents with OpenAI ...")
        self._index = VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            show_progress=True,
        )
        print(f"[OK] Index built and stored in Redis  (index={index_name})")
        return self._index

    def load_index(self, index_name: str = INDEX_NAME) -> VectorStoreIndex:
        """
        Load a previously created index from Redis without re-embedding.

        Raises RuntimeError if no index exists - run create_index() first.
        """
        print(f"Loading existing index from Redis  [{index_name}] ...")
        try:
            self._vector_store = RedisVectorStore(redis_url=self.redis_url)
            self._index        = VectorStoreIndex.from_vector_store(self._vector_store)
            print("[OK] Index loaded from Redis")
            return self._index
        except Exception as exc:
            raise RuntimeError(
                f"Could not load index from Redis. "
                f"Run create_index() first.\nError: {exc}"
            ) from exc

    def is_index_ready(self) -> bool:
        """Safe readiness check for debugging and control flow."""
        return self._index is not None

    # -------------------------------------------------------------------------
    # Search
    # -------------------------------------------------------------------------

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """
        Semantic search across all knowledge bases.

        Args:
            query : Natural language question.
            top_k : Maximum number of results to return.

        Returns:
            List of result dicts, each containing:
                question, answer, category, doc_type, source, score, relevance
                + any extra metadata fields present in the source CSV.
        """
        print(f"[SearchService] index_ready_before_search={self.is_index_ready()}")

        if self._index is None:
            try:
                self.load_index()
            except Exception:
                pass

        if self._index is None:
            self.create_index()

        query_engine = self._index.as_query_engine(
            similarity_top_k=top_k,
            response_mode="no_text",
        )
        response = query_engine.query(query)
       # print(f"[SearchService] source_nodes={len(response.source_nodes)}")

        results: List[Dict[str, Any]] = []
        for node in response.source_nodes:
            meta  = node.metadata or {}
            score = float(node.score) if node.score is not None else 0.0

            result: Dict[str, Any] = {
                "question":  meta.get("primary",  node.text[:200]),
                "answer":    meta.get("answer",   ""),
                "category":  meta.get("category", "general"),
                "doc_type":  meta.get("doc_type", "faq"),
                "source":    meta.get("source",   "unknown"),
                "score":     round(score, 4),
                "relevance": (
                    "High"   if score >= 0.80 else
                    "Medium" if score >= 0.55 else
                    "Low"
                ),
            }

            for key, val in meta.items():
                if key not in result:
                    result[key] = val

            results.append(result)

        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:top_k]

    def search_by_category(
        self,
        query:    str,
        category: str,
        top_k:    int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Semantic search filtered to a specific category or knowledge base.

        Args:
            query    : Natural language question.
            category : e.g. 'faq' | 'amenities' | 'services' | 'booking' |
                       'Spa Services' (any category value from the CSV).
            top_k    : Maximum results after filtering.
        """
        candidates = self.search(query, top_k=top_k * 4)
        filtered   = [
            r for r in candidates
            if r.get("category", "").lower() == category.lower()
            or r.get("doc_type",  "").lower() == category.lower()
        ]
        return filtered[:top_k]

    def explain_results(
        self,
        query:   str,
        results: List[Dict[str, Any]],
        top_k:   int = 10,
    ) -> str:
        """
        Send the top-k search results to OpenAI and generate a fluent,
        guest-facing answer grounded in the retrieved knowledge-base content.

        Args:
            query   : The original guest question.
            results : List of result dicts returned by search() or
                      search_by_category().
            top_k   : How many of the top results to include as context
                      (default 10).

        Returns:
            A natural-language answer string.
        """
        if not results:
            return (
                "I'm sorry, I couldn't find any relevant information for your question. "
                "Please contact our front desk for assistance."
            )

        # Build a compact context block from the top results
        context_parts: List[str] = []
        for i, r in enumerate(results[:top_k], 1):
            question = r.get("question", "").strip()
            answer   = r.get("answer",   "").strip()
            category = r.get("category", "").strip()
            score    = r.get("score",    0.0)

            # Build extra detail line from amenity/service metadata if present
            extras: List[str] = []
            for field in ("price", "duration", "availability", "location",
                          "booking_required", "duration_minutes", "department"):
                val = r.get(field)
                if val and str(val).lower() not in ("none", "nan", ""):
                    extras.append(f"{field}: {val}")

            block = f"[Source {i}] category={category}  score={score:.3f}"
            if question:
                block += f"\n  Q: {question}"
            if answer:
                block += f"\n  A: {answer}"
            if extras:
                block += f"\n  Details: {', '.join(extras)}"

            context_parts.append(block)

        context_text = "\n\n".join(context_parts)
        user_prompt  = (
            f"Guest question: {query}\n\n"
            f"Knowledge base excerpts:\n{context_text}\n\n"
            "Please answer the guest's question using the excerpts above."
        )

        try:
            response = self._openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _FAQ_EXPLAIN_SYSTEM_PROMPT},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=0.4,
                max_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            print(f"[SearchService] explain_results error: {exc}")
            # Graceful fallback: return the top answer verbatim
            top = results[0]
            return top.get("answer") or top.get("question") or "Please contact the front desk for more information."


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_search_service: Optional[HotelFAQSearchService] = None


def get_search_service() -> HotelFAQSearchService:
    """Return a cached HotelFAQSearchService instance."""
    global _search_service
    if _search_service is None:
        _search_service = HotelFAQSearchService()
    return _search_service