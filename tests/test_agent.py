"""Research loop tested without Ollama: the LLM is a scripted fake, the MCP server runs in-process."""
import asyncio

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel

import agent


class Hit(BaseModel):
    id: int
    source: str
    title: str
    text: str


class SearchResult(BaseModel):
    hits: list[Hit]


STOP = Hit(id=1, source="docs/runbook.md#stop", title="Stop", text="Run docker compose stop.")
COST = Hit(id=2, source="docs/aws.md#cost", title="Cost", text="0.03 USD per hour.")


def make_server(queries: list | None = None) -> MCPServer:
    """A fake docs server; every query it receives is appended to `queries`."""
    server = MCPServer("fake-docs", instructions="Fake instructions.")

    @server.tool()
    def search_docs(query: str) -> SearchResult:
        """Search the documentation."""
        if queries is not None:
            queries.append(query)
        return SearchResult(hits=[COST if "cost" in query else STOP])

    return server


def script(monkeypatch, replies, language="English"):
    """Make agent.chat return the given messages one after the other, recording what it was sent.

    The call that detects the language is answered apart and is not recorded.
    """
    seen = []

    async def fake_chat(messages, tools, max_tokens, schema=None):
        if schema:
            return {"role": "assistant", "content": f'{{"language": "{language}"}}'}
        seen.append({"messages": list(messages), "tools": tools})
        return replies[len(seen) - 1]

    async def fake_chat_stream(messages, max_tokens):
        # the answer arrives in two pieces, like tokens from a real model
        seen.append({"messages": list(messages), "tools": []})
        content = replies[len(seen) - 1]["content"]
        for piece in (content[: len(content) // 2], content[len(content) // 2:]):
            if piece:
                yield piece

    monkeypatch.setattr(agent, "chat", fake_chat)
    monkeypatch.setattr(agent, "chat_stream", fake_chat_stream)
    return seen


def calls(*named):
    """An assistant message with one tool call per (name, arguments) pair."""
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": arguments}} for name, arguments in named],
    }


def search(query):
    return calls(("search_docs", {"query": query}))


def finish(missing=""):
    return calls(("finish", {"missing": missing}))


def says(text):
    return {"role": "assistant", "content": text}


def run(question="How do I stop it?", queries=None):
    return asyncio.run(agent.ask(question, make_server(queries)))


def last_tool_result(seen_call):
    return seen_call["messages"][-1]["content"]


def test_finish_leaves_the_loop_and_the_answer_is_written_from_the_excerpts(monkeypatch):
    seen = script(monkeypatch, [search("stop cluster"), search("cost"), finish(), says("Run docker compose stop [1].")])

    reply = run()

    assert reply["answer"] == "Run docker compose stop [1]."
    assert reply["finished_by"] == "finish"
    assert reply["sources"] == ["docs/runbook.md#stop", "docs/aws.md#cost"]
    assert [step["tool"] for step in reply["steps"]] == ["search_docs", "search_docs", "finish"]
    # the MCP tools are discovered at runtime and offered together with the agent's own finish
    assert [tool["function"]["name"] for tool in seen[0]["tools"]] == ["search_docs", "finish"]
    # the server explains its tools, and the agent passes that on to the model
    assert "Fake instructions." in seen[0]["messages"][0]["content"]
    # the answer is written in a new conversation: only the numbered excerpts and the question, no tools
    system, user = seen[-1]["messages"]
    assert "[1] docs/runbook.md#stop" in user["content"] and "[2] docs/aws.md#cost" in user["content"]
    assert user["content"].endswith("Question: How do I stop it?")
    assert seen[-1]["tools"] == []


def test_research_reports_every_step_then_the_answer_in_pieces_then_a_summary(monkeypatch):
    script(monkeypatch, [search("stop cluster"), search("cost"), finish(), says("Run docker compose stop [1].")])

    async def collect():
        return [event async for event in agent.research("How do I stop it?", make_server())]

    events = asyncio.run(collect())

    assert [event["type"] for event in events] == ["step", "step", "step", "sources", "answer", "answer", "done"]
    assert events[0] == {"type": "step", "tool": "search_docs", "arguments": {"query": "stop cluster"}, "new_excerpts": 1}
    assert events[3]["sources"] == ["docs/runbook.md#stop", "docs/aws.md#cost"]
    pieces = [event["text"] for event in events if event["type"] == "answer"]
    assert "".join(pieces) == events[-1]["answer"] == "Run docker compose stop [1]."


def test_answer_is_requested_in_the_language_of_the_question(monkeypatch):
    seen = script(monkeypatch, [search("stop"), search("cost"), finish(), says("Ecco.")], language="Italian")

    run("Come lo fermo?")

    assert "Reply in Italian." in seen[-1]["messages"][0]["content"]


def test_finish_is_refused_until_the_model_has_searched_twice(monkeypatch):
    seen = script(monkeypatch, [finish(), search("stop"), finish(), search("cost"), finish(), says("Done.")])

    reply = run()

    assert last_tool_result(seen[1]) == agent.TOO_EARLY
    assert last_tool_result(seen[3]) == agent.TOO_EARLY
    assert reply["finished_by"] == "finish"
    # the trace says which calls were turned down, and the accepted finish is not marked
    assert [step.get("refused") for step in reply["steps"]] == ["too_early", None, "too_early", None, None]


def test_finish_with_something_missing_sends_the_model_back_to_search(monkeypatch):
    seen = script(monkeypatch, [
        search("stop"), search("stop now"), finish("the cost per hour"), search("cost"), finish(), says("Done."),
    ])

    reply = run()

    assert last_tool_result(seen[3]) == agent.NOT_YET.format(missing="the cost per hour")
    assert reply["steps"][2]["refused"] == "missing"
    assert reply["sources"] == ["docs/runbook.md#stop", "docs/aws.md#cost"]
    assert reply["finished_by"] == "finish"


def test_text_written_inside_the_loop_ends_it_and_is_not_the_answer(monkeypatch):
    seen = script(monkeypatch, [search("stop"), says("I think the answer is..."), says("Run docker compose stop [1].")])

    reply = run()

    assert reply["answer"] == "Run docker compose stop [1]."
    assert reply["finished_by"] == "answer"
    assert len(seen) == 3


def test_out_of_steps_ends_the_loop(monkeypatch):
    searches = [search(f"attempt {i}") for i in range(agent.MAX_STEPS)]
    seen = script(monkeypatch, searches + [says("Final.")])

    reply = run()

    assert reply["answer"] == "Final."
    assert reply["finished_by"] == "max_steps"
    assert len(reply["steps"]) == agent.MAX_STEPS


def test_same_query_in_another_word_order_is_not_executed_twice(monkeypatch):
    seen = script(monkeypatch, [search("Stop Cluster"), search("cluster stop"), says(""), says("Done.")])
    queries = []

    reply = run(queries=queries)

    assert queries == ["Stop Cluster"]
    assert last_tool_result(seen[2]) == agent.REPEATED
    assert reply["steps"][1]["refused"] == "repeated"


def test_excerpts_already_read_are_not_shown_again(monkeypatch):
    seen = script(monkeypatch, [search("stop"), search("stop it now"), search("cost"), finish(), says("Done.")])

    reply = run()

    assert [step.get("new_excerpts") for step in reply["steps"]] == [1, 0, 1, None]
    assert last_tool_result(seen[2]) == agent.NOTHING_NEW
    assert last_tool_result(seen[3]).startswith("[2] docs/aws.md#cost")
    # each excerpt reaches the answer step once
    assert seen[-1]["messages"][1]["content"].count("docs/runbook.md#stop") == 1


def test_only_the_first_call_of_a_step_is_executed(monkeypatch):
    both = calls(("search_docs", {"query": "stop"}), ("search_docs", {"query": "cost"}))
    seen = script(monkeypatch, [both, says(""), says("Done.")])
    queries = []

    reply = run(queries=queries)

    assert queries == ["stop"]
    assert len(reply["steps"]) == 1
    assert len(seen[1]["messages"][2]["tool_calls"]) == 1


def test_unknown_tool_is_reported_to_the_model_instead_of_crashing(monkeypatch):
    seen = script(monkeypatch, [calls(("does_not_exist", {})), says(""), says("I could not find it.")])

    reply = run()

    assert reply["answer"] == "I could not find it."
    assert last_tool_result(seen[1]).startswith("Tool error")
    assert "(nothing was found)" in seen[-1]["messages"][1]["content"]


def test_excerpts_stop_when_the_context_budget_is_used_up(monkeypatch):
    monkeypatch.setattr(agent, "EXCERPT_BUDGET", len(STOP.text))
    seen = script(monkeypatch, [search("stop"), search("cost"), finish(), says("Done.")])

    reply = run()

    assert last_tool_result(seen[2]) == agent.CONTEXT_FULL
    assert reply["sources"] == ["docs/runbook.md#stop"]


def test_advice_and_section_names_of_an_empty_result_reach_the_model():
    text, added = agent._excerpts({"hits": [], "note": "Nothing has this name.", "sections": ["A", "B > C"]}, agent.Notes())

    assert text == "Nothing has this name.\n\nSections you can open by name: A; B > C"
    assert added == 0


def test_language_falls_back_when_the_model_does_not_return_the_json(monkeypatch):
    async def broken_chat(messages, tools, max_tokens, schema=None):
        return {"role": "assistant", "content": "Italian, I think"}

    monkeypatch.setattr(agent, "chat", broken_chat)

    assert asyncio.run(agent._language("Come va?")) == "the language of the question"
