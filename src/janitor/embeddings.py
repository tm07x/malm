import os
import struct

import httpx

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-3-large"
DIMENSIONS = 1024

# Instruction prefixes — inlined into text since Voyage doesn't support a prompt param.
# These steer the embedding space toward our classification domain.
DOC_PREFIX = "Categorize this Norwegian legal, financial, or corporate document: "
QUERY_PREFIX = "Search for Norwegian legal, financial, or corporate documents about: "


def get_embeddings(
    texts: list[str],
    input_type: str = "document",
    use_prefix: bool = True,
) -> list[list[float]]:
    api_key = os.environ.get("VOYAGE_API_KEY")
    if not api_key:
        raise RuntimeError("VOYAGE_API_KEY not set")

    if use_prefix:
        prefix = DOC_PREFIX if input_type == "document" else QUERY_PREFIX
        texts = [prefix + t for t in texts]

    # Voyage voyage-3-large has a ~16k token limit per text. Truncate long texts.
    texts = [t[:12000] for t in texts]

    resp = httpx.post(
        VOYAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={"input": texts, "model": MODEL, "input_type": input_type},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [item["embedding"] for item in sorted(data, key=lambda x: x["index"])]


def get_embedding(text: str, input_type: str = "document", use_prefix: bool = True) -> list[float]:
    return get_embeddings([text], input_type, use_prefix)[0]


def build_doc_text(filename: str, content: dict | None = None, max_content: int = 800) -> str:
    """Build embedding text for a file. Weights content over filename for opaque names."""
    parts = []

    # Content first — dominates for opaque filenames
    if content:
        sheets = content.get("sheet_names", [])
        if sheets:
            parts.append(f"Sheets: {', '.join(sheets)}")

        headers = content.get("headers", {})
        for sheet, cols in headers.items():
            non_empty = [c for c in cols if c]
            if non_empty:
                parts.append(f"Columns: {', '.join(non_empty[:20])}")

        values = content.get("cell_values", [])
        if values:
            parts.append(" ".join(values[:max_content]))

    # Filename last — supplement, not primary signal
    parts.append(f"Filename: {filename}")

    return "\n".join(parts)


def serialize_f32(vec: list[float]) -> bytes:
    return struct.pack(f"{len(vec)}f", *vec)


def deserialize_f32(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"{n}f", blob))
