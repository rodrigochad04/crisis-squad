"""RAG knowledge base — FAISS + LangChain.

Indexes markdown documents (runbooks, postmortems, alert patterns) locally.
Uses `sentence-transformers` for embeddings — no external embedding API needed.

Usage:
    from src.knowledge_base.retriever import get_retriever
    retriever = get_retriever()
    docs = retriever.invoke("JVM heap exhaustion checkout-service rollback")
"""

from __future__ import annotations

from pathlib import Path

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_text_splitters import RecursiveCharacterTextSplitter

try:
    from langchain_huggingface import HuggingFaceEmbeddings  # preferred (no deprecation warning)
except ImportError:
    from langchain_community.embeddings import (  # type: ignore[assignment,no-redef]
        HuggingFaceEmbeddings,
    )
from langchain_core.vectorstores import VectorStoreRetriever

from src.config import settings

_EMBED_MODEL = "BAAI/bge-small-en-v1.5"  # 33M params, fast, runs locally
_TOP_K = 5

_retriever_singleton: VectorStoreRetriever | None = None


def _embeddings() -> HuggingFaceEmbeddings:
    return HuggingFaceEmbeddings(
        model_name=_EMBED_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def build_index(docs_dir: str | None = None, persist_dir: str | None = None) -> FAISS:
    """Load documents, split, embed and persist the FAISS index."""
    docs_path = Path(docs_dir or settings.kb_docs_dir)
    persist_path = Path(persist_dir or settings.kb_persist_dir)

    loader = DirectoryLoader(
        str(docs_path),
        glob="**/*.md",
        loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
        show_progress=True,
    )
    raw_docs = loader.load()

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=400,
        chunk_overlap=50,
        separators=["\n## ", "\n### ", "\n\n", "\n", " "],
    )
    chunks = splitter.split_documents(raw_docs)

    emb = _embeddings()
    store = FAISS.from_documents(chunks, emb)
    persist_path.mkdir(parents=True, exist_ok=True)
    store.save_local(str(persist_path))
    return store


def load_index(persist_dir: str | None = None) -> FAISS:
    """Load an existing FAISS index from disk."""
    persist_path = Path(persist_dir or settings.kb_persist_dir)
    emb = _embeddings()
    return FAISS.load_local(str(persist_path), emb, allow_dangerous_deserialization=True)


def get_retriever(force_rebuild: bool = False) -> VectorStoreRetriever:
    """Return the module-level retriever singleton.

    Builds the index on first call if it does not exist.
    Use force_rebuild=True after adding new documents.
    """
    global _retriever_singleton
    if _retriever_singleton is not None and not force_rebuild:
        return _retriever_singleton

    persist_path = Path(settings.kb_persist_dir)
    if persist_path.exists() and not force_rebuild:
        store = load_index()
    else:
        store = build_index()

    _retriever_singleton = store.as_retriever(
        search_type="mmr",  # Maximal Marginal Relevance — reduces redundancy
        search_kwargs={"k": _TOP_K, "fetch_k": 20},
    )
    return _retriever_singleton
