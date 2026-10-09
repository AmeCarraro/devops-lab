"""MCP server "docs": exposes the documentation search as tools.

Any MCP client can use it; our agent (app/agent.py) is one of them.
The transport is Streamable HTTP, so it runs as a normal web service in Kubernetes.
"""
import os
from typing import Annotated

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import BaseModel, Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from index import Chunk, DocsIndex

index = DocsIndex(
    docs_dir=os.getenv("DOCS_DIR", "docs"),
    ollama_url=os.getenv("OLLAMA_URL", "http://127.0.0.1:11434"),
    model=os.getenv("EMBED_MODEL", "nomic-embed-text"),
)

# Sent to every client when it connects: how to use the tools is knowledge of
# the server, so it lives here and not in the prompt of each agent
INSTRUCTIONS = (
    "Documentation of the devops-lab project: markdown pages split into sections. "
    "search_docs finds sections by meaning: write the query in English, "
    "as a short phrase of a few words and not a single word. "
    "search_by_name opens sections by the name of their page or heading, for example 'troubleshooting' "
    "or 'Stop the cluster': use it only with a name you have seen, never with a topic or a question."
)

mcp = MCPServer("docs", instructions=INSTRUCTIONS)


class Hit(BaseModel):
    id: int = Field(description="Identifier of the excerpt, the same in every search")
    source: str = Field(description="File and section the excerpt comes from")
    title: str = Field(description="Heading trail of the section")
    text: str
    score: float = Field(description="1 is a perfect match")


class SearchResult(BaseModel):
    hits: list[Hit]
    sections: list[str] = Field(default=[], description="Names of other sections that search_by_name can open")
    note: str = Field(default="", description="Advice for the caller when there are no hits")


def _hit(chunk: Chunk, score: float) -> Hit:
    return Hit(id=chunk.id, source=chunk.source, title=chunk.title, text=chunk.text, score=round(score, 3))


@mcp.tool()
async def search_docs(
    query: Annotated[str, Field(description="What to look for, in English")],
    k: Annotated[int, Field(description="How many excerpts to return")] = 4,
) -> SearchResult:
    """Search the documentation by meaning and return the most relevant excerpts with their source."""
    results = await index.search(query, max(1, min(k, 8)))
    return SearchResult(hits=[_hit(chunk, score) for chunk, score in results])


@mcp.tool()
def search_by_name(
    name: Annotated[str, Field(description="Name of a page or of a heading, or some words of it")],
) -> SearchResult:
    """Open documentation sections by the name of their page or heading. It does not search by meaning."""
    matches = index.by_name(name)
    if not matches:
        # nothing has that name: answer with the names that exist, so the caller can pick one
        return SearchResult(
            hits=[],
            sections=sorted({chunk.title for chunk in index.chunks})[:40],
            note="No page or heading has this name. Search by meaning with search_docs instead.",
        )
    return SearchResult(
        hits=[_hit(chunk, score) for chunk, score in matches[:4]],
        sections=sorted({chunk.title for chunk, _ in matches[4:]}),
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "indexed_chunks": len(index.chunks)})


if __name__ == "__main__":
    # The SDK rejects requests whose Host header is not listed (DNS rebinding protection)
    allowed_hosts = os.getenv("ALLOWED_HOSTS", "docs-mcp:8001,127.0.0.1:*,localhost:*").split(",")
    mcp.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8001")),
        # no server-side sessions and plain JSON replies: any replica can serve any request
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(allowed_hosts=allowed_hosts),
    )
