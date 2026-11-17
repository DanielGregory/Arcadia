"""Turn dreams into vectors, so similar dreams sit close together.

An embedding model (sentence-transformers all-MiniLM-L6-v2: small, fast on a
CPU, 384 numbers per text) reads a dream and returns a point in a
384-dimensional space where texts about similar things land near each other.
"Near" is measured by cosine similarity: 1 = the same direction, 0 = unrelated.
The vectors are normalised to length 1, so cosine similarity is just a dot product.

    from engine.memory.embed import embed
    vecs = embed(["I climbed the stairs to the temple", "a ship in the harbour"])   # (2, 384)
"""

from __future__ import annotations

MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_model = None


def embed(texts: list[str], device: str = "cpu"):
    """(len(texts), 384) numpy array of unit vectors. The model loads once and is reused."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(MODEL, device=device)
    # MiniLM reads at most 256 word pieces (~180 words); longer dreams are judged by their opening.
    return _model.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False)


def to_pg(vec) -> str:
    """A vector as pgvector's text form, "[0.1,0.2,...]", which the REST API accepts."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
