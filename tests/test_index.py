from index import MAX_CHARS, chunk_markdown, find_by_name

DOC = """# Runbook

Intro text.

## Stop the cluster

Run this:

```bash
# this comment is not a heading
docker compose stop
```

### Details

Data is kept.

## Start
Run deploy.
"""


def test_chunks_follow_headings():
    chunks = chunk_markdown("docs/runbook.md", DOC)
    assert [c.title for c in chunks] == [
        "Runbook",
        "Runbook > Stop the cluster",
        "Runbook > Stop the cluster > Details",
        "Runbook > Start",
    ]
    assert chunks[1].source == "docs/runbook.md#stop-the-cluster"


def test_comment_in_code_block_is_not_a_heading():
    chunks = chunk_markdown("docs/runbook.md", DOC)
    assert "# this comment is not a heading" in chunks[1].text


def test_long_section_is_split_without_cutting_code_blocks():
    code = "```\n" + "\n\n".join(["line"] * 50) + "\n```"
    paragraphs = "\n\n".join(["word " * 100] * 4)
    chunks = chunk_markdown("docs/big.md", f"# Big\n\n{paragraphs}\n\n{code}\n")
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    # every chunk has balanced fences, so no block was cut in half
    assert all(c.text.count("```") % 2 == 0 for c in chunks)


def titles_named(name):
    return [chunk.title for chunk, _ in find_by_name(chunk_markdown("docs/runbook.md", DOC), name)]


def test_find_by_name_matches_a_heading_and_its_subsections():
    assert titles_named("Stop the cluster") == [
        "Runbook > Stop the cluster",
        "Runbook > Stop the cluster > Details",
    ]


def test_find_by_name_matches_the_file_name():
    assert len(titles_named("runbook page")) == 4


def test_find_by_name_keeps_only_the_best_matches():
    # "details" and "start" are in different sections: each matches one word of two,
    # while no section matches both, so both are returned as equally good
    assert titles_named("details start") == ["Runbook > Stop the cluster > Details", "Runbook > Start"]
    # here one section matches both words and wins over the ones matching only "cluster"
    assert titles_named("cluster details") == ["Runbook > Stop the cluster > Details"]


def test_find_by_name_ignores_plural_and_case():
    assert titles_named("CLUSTERS") == titles_named("cluster")


def test_find_by_name_returns_nothing_for_an_unknown_name():
    assert titles_named("kubernetes") == []
    assert titles_named("the page") == []
