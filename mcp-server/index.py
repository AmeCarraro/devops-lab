"""Markdown -> chunks -> two ways to find them: by meaning (embeddings) and by name.

Small on purpose: the whole index is a numpy matrix in memory, built on first use.
Fine for a few thousand chunks; a vector database replaces this file when the corpus grows.
"""
import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx2
import numpy as np

MAX_CHARS = 1200
HEADING = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")

# nomic-embed-text is trained with these task prefixes: documents and queries
# must be embedded differently or retrieval quality drops
DOC_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "

# words that do not say which page or section is wanted
NAME_STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "and", "or", "for", "is", "about",
    "page", "section", "file", "doc", "docs", "document", "md",
}


@dataclass
class Chunk:
    source: str  # file + section anchor: what a person opens to verify the answer
    title: str  # heading trail, e.g. "Runbook > Stop the cluster"
    text: str
    id: int = -1  # position in the index, set by load_chunks


def _slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def _is_fence(line: str) -> bool:
    return line.lstrip().startswith("```")


def _split_long(body: str) -> list[str]:
    """Pack paragraphs into pieces of at most MAX_CHARS, never cutting inside a code block."""
    if len(body) <= MAX_CHARS:
        return [body]

    paragraphs, current, in_fence = [], [], False
    for line in body.splitlines():
        if _is_fence(line):
            in_fence = not in_fence
        if line.strip() or in_fence:
            current.append(line)
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))

    pieces, buffer = [], ""
    for paragraph in paragraphs:
        if buffer and len(buffer) + len(paragraph) + 2 > MAX_CHARS:
            pieces.append(buffer)
            buffer = paragraph
        else:
            buffer = f"{buffer}\n\n{paragraph}" if buffer else paragraph
    if buffer:
        pieces.append(buffer)
    return pieces


def chunk_markdown(source: str, markdown: str) -> list[Chunk]:
    """Split a markdown file at its headings, so every chunk is one coherent section."""
    chunks: list[Chunk] = []
    trail: list[str] = []
    lines: list[str] = []
    in_fence = False

    def flush():
        body = "\n".join(lines).strip()
        lines.clear()
        if not body:
            return
        title = " > ".join(trail) or source
        anchor = f"{source}#{_slug(trail[-1])}" if trail else source
        chunks.extend(Chunk(anchor, title, piece) for piece in _split_long(body))

    for line in markdown.splitlines():
        if _is_fence(line):
            in_fence = not in_fence
        # a "# comment" inside a code block is not a heading
        match = None if in_fence else HEADING.match(line)
        if match:
            flush()
            level = len(match.group(1))
            del trail[level - 1:]
            trail.append(match.group(2))
        else:
            lines.append(line)
    flush()
    return chunks


def load_chunks(docs_dir: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(docs_dir.rglob("*.md")):
        source = f"{docs_dir.name}/{path.relative_to(docs_dir).as_posix()}"
        chunks.extend(chunk_markdown(source, path.read_text(encoding="utf-8")))
    for position, chunk in enumerate(chunks):
        chunk.id = position
    return chunks


def _name_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower())) - NAME_STOPWORDS


def _same_word(a: str, b: str) -> bool:
    # "pod" also finds "pods", "embedding" also finds "embeddings"
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def find_by_name(chunks: list[Chunk], name: str) -> list[tuple[Chunk, float]]:
    """Chunks whose file name or headings contain the words of `name`. Only the best matches are returned."""
    wanted = _name_words(name)
    scored = []
    for chunk in chunks:
        file_name = chunk.source.split("#")[0].rsplit("/", 1)[-1].removesuffix(".md")
        names = _name_words(f"{file_name} {chunk.title}")
        matched = sum(any(_same_word(word, other) for other in names) for word in wanted)
        if matched:
            scored.append((chunk, matched / len(wanted)))
    best = max((score for _, score in scored), default=0)
    return [(chunk, score) for chunk, score in scored if score == best]


class DocsIndex:
    def __init__(self, docs_dir: str, ollama_url: str, model: str):
        self.docs_dir = Path(docs_dir)
        self.ollama_url = ollama_url.rstrip("/")
        self.model = model
        self.chunks: list[Chunk] = []
        self._vectors: np.ndarray | None = None
        self._lock = asyncio.Lock()

    def _load(self):
        if not self.chunks:
            self.chunks = load_chunks(self.docs_dir)
        if not self.chunks:
            raise RuntimeError(f"no markdown files found in {self.docs_dir}")

    async def _embed(self, texts: list[str]) -> np.ndarray:
        vectors = []
        async with httpx2.AsyncClient(timeout=120) as client:
            for start in range(0, len(texts), 32):
                response = await client.post(
                    f"{self.ollama_url}/api/embed",
                    json={
                        "model": self.model,
                        "input": texts[start:start + 32],
                        # Embeddings on CPU: the embedding model is tiny, and on a 4 GB GPU
                        # Ollama would otherwise unload the chat model to make room for it
                        "options": {"num_gpu": 0},
                    },
                )
                response.raise_for_status()
                vectors.extend(response.json()["embeddings"])
        matrix = np.asarray(vectors, dtype=np.float32)
        # unit vectors: the dot product below is then the cosine similarity
        return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)

    async def _ensure_built(self):
        async with self._lock:
            if self._vectors is not None:
                return
            self._load()
            self._vectors = await self._embed([f"{DOC_PREFIX}{c.title}\n{c.text}" for c in self.chunks])

    async def search(self, query: str, k: int) -> list[tuple[Chunk, float]]:
        await self._ensure_built()
        query_vector = (await self._embed([QUERY_PREFIX + query]))[0]
        scores = self._vectors @ query_vector
        best = np.argsort(-scores)[:k]
        return [(self.chunks[i], float(scores[i])) for i in best]

    def by_name(self, name: str) -> list[tuple[Chunk, float]]:
        # needs no embeddings, so it works even when the LLM server is down
        self._load()
        return find_by_name(self.chunks, name)
