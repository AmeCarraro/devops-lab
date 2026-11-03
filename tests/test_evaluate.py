"""The evaluation's own checks: cases, scoring, report, and the gate of the pipeline."""
from pathlib import Path

import pytest
from pydantic import ValidationError

import evaluate
from evaluate import Case, Reply, Verdict
from index import load_chunks

DOCS = Path(__file__).resolve().parent.parent / "docs"


def test_every_case_is_valid_and_names_sections_that_exist():
    # a renamed heading would otherwise turn a right answer into a fail without anyone noticing
    sections = {chunk.source for chunk in load_chunks(DOCS)}
    cases = evaluate.load_cases()

    assert len(cases) >= 20
    assert any(not case.answerable for case in cases)
    for case in cases:
        assert set(case.sources) <= sections, case.id


def test_a_case_must_say_how_it_is_checked():
    with pytest.raises(ValidationError):
        Case(id="x", question="?", sources=["docs/a.md#b"])  # no facts
    with pytest.raises(ValidationError):
        Case(id="x", question="?", answerable=False, facts=[["y"]])


def test_facts_ignore_case_spaces_and_the_kind_of_slash():
    answer = "Run `docker compose -f local\\compose.yaml   STOP`."

    assert evaluate.has_fact(answer, ["local/compose.yaml stop"])
    assert not evaluate.has_fact(answer, ["down -v"])


def test_citations_are_read_by_their_number():
    sources = ["docs/a.md#one", "docs/a.md#two", "docs/b.md#three"]

    assert evaluate.cited_sources("See [2].", sources) == {"docs/a.md#two"}
    assert evaluate.cited_sources("As [1][3] and [1, 2] say", sources) == set(sources)
    assert evaluate.cited_sources("Out of range [7], none [x]", sources) == set()


CASE = Case(id="stop", question="How do I stop it?", sources=["docs/l.md#stop"], facts=[["compose stop"]])


def reply(answer, sources=("docs/l.md#other", "docs/l.md#stop"), finished_by="finish"):
    return Reply(answer=answer, sources=list(sources), finished_by=finished_by, steps=[{}, {}], seconds=3)


def test_a_right_answer_passes():
    result = evaluate.score(CASE, reply("Use `docker compose stop` [2]."), None)

    assert result.passed and result.retrieved and result.cited
    assert (result.facts_found, result.facts_total) == (1, 1)


def test_the_right_section_read_but_not_cited_fails():
    # what happened on EC2 on 2026-11-03: the answer copied the excerpt of another section
    result = evaluate.score(CASE, reply("Use `docker compose stop` [1]."), None)

    assert result.retrieved and not result.cited and not result.passed


def test_a_missing_fact_fails():
    result = evaluate.score(CASE, reply("Stop the container [2]."), None)

    assert result.cited and result.facts_found == 0 and not result.passed


def test_an_unanswerable_case_passes_only_when_the_agent_says_it_does_not_know():
    case = Case(id="azure", question="How do I deploy to Azure?", answerable=False)
    honest = Verdict(says_not_covered=True, reason="it says so")
    invented = Verdict(says_not_covered=False, reason="it explains steps")

    assert evaluate.score(case, reply("The excerpts do not cover Azure."), honest).passed
    assert not evaluate.score(case, reply("Run az aks create [1]."), invented).passed


def test_the_judge_reply_is_validated():
    assert Verdict.model_validate_json('{"says_not_covered": true, "reason": "ok"}').says_not_covered
    with pytest.raises(ValidationError):
        Verdict.model_validate_json('{"says_not_covered": "maybe"}')


def test_the_report_adds_up():
    unanswerable = Case(id="none", question="?", answerable=False)
    results = [
        evaluate.score(CASE, reply("`docker compose stop` [2]"), None),
        evaluate.score(CASE, reply("no idea", sources=[], finished_by="max_steps"), None),
        evaluate.score(unanswerable, reply("Not covered."), Verdict(says_not_covered=True, reason="")),
    ]

    report = evaluate.report("m", results)

    assert report.pass_rate == pytest.approx(0.667)
    assert report.retrieval == 0.5 and report.citation == 0.5 and report.facts == 0.5
    assert report.abstention == 1.0
    assert report.finished_by == {"finish": 2, "max_steps": 1}


def test_the_gate_fails_under_the_minimum(monkeypatch, tmp_path):
    failing = evaluate.report("m", [evaluate.score(CASE, reply("nothing"), None)])
    monkeypatch.setattr(evaluate, "run", lambda *args: failing)

    assert evaluate.main(["--min-pass", "0.5", "--out", str(tmp_path / "r.json")]) == 1
    assert evaluate.main(["--min-pass", "0"]) == 0
    assert '"pass_rate": 0.0' in (tmp_path / "r.json").read_text()
