"""The MCP server seen from a client, in-process. Name search needs no embeddings, so no Ollama."""
import asyncio

from mcp import Client

import server
from index import DocsIndex

DOC = """# Runbook

Intro text.

## Stop the cluster

Run docker compose stop.

## Start

Run deploy.
"""


def call(monkeypatch, tmp_path, name):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "runbook.md").write_text(DOC, encoding="utf-8")
    monkeypatch.setattr(server, "index", DocsIndex(str(docs), "http://unused", "unused"))

    async def run():
        async with Client(server.mcp) as client:
            tools = [tool.name for tool in (await client.list_tools()).tools]
            result = await client.call_tool("search_by_name", {"name": name})
            return tools, client.instructions, result.structured_content

    return asyncio.run(run())


def test_server_offers_both_searches_and_explains_them(monkeypatch, tmp_path):
    tools, instructions, _ = call(monkeypatch, tmp_path, "runbook")

    assert tools == ["search_docs", "search_by_name"]
    assert "search_docs" in instructions and "search_by_name" in instructions


def test_search_by_name_opens_the_section_with_that_heading(monkeypatch, tmp_path):
    _, _, result = call(monkeypatch, tmp_path, "Stop the cluster")

    assert [hit["source"] for hit in result["hits"]] == ["docs/runbook.md#stop-the-cluster"]
    assert result["hits"][0]["text"] == "Run docker compose stop."


def test_search_by_name_with_an_unknown_name_lists_the_names_that_exist(monkeypatch, tmp_path):
    _, _, result = call(monkeypatch, tmp_path, "kubernetes")

    assert result["hits"] == []
    assert result["sections"] == ["Runbook", "Runbook > Start", "Runbook > Stop the cluster"]
    assert "search_docs" in result["note"]
