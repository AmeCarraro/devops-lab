"""Evaluation of the documentation agent: fixed questions, scored answers, a pass or a fail.

Every case in cases.json is a question about the documentation in docs/. An answerable case
names the sections that answer it and the facts the answer must contain; an unanswerable
one (nothing in the documentation answers it) passes when the agent says so instead of
guessing. Three checks are plain code, so they cost nothing and never change their mind:

- retrieved: one of the right sections is among the sources the research read
- cited: the answer cites one of the right sections, by its number
- facts: every fact appears in the answer (each fact is a list of accepted spellings)

The fourth, whether the answer admits that the documentation does not cover the question,
is asked to an LLM judge whose reply is forced into the `Verdict` schema and validated by
pydantic.

Usage, against a running agent (the local cluster, or EC2 through its address):
    python eval/evaluate.py --url http://127.0.0.1:8080
    python eval/evaluate.py --url ... --min-pass 0.6 --pushgateway http://...:9091
The exit code is 1 when the pass rate is under --min-pass: that is what fails the pipeline.
"""
import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx2
from prometheus_client import CollectorRegistry, Gauge, push_to_gateway
from pydantic import BaseModel, Field, ValidationError, model_validator

CASES = Path(__file__).with_name("cases.json")


class Case(BaseModel):
    id: str
    question: str
    answerable: bool = True
    sources: list[str] = []
    facts: list[list[str]] = Field(default=[], description="Each fact: the spellings that count as present")

    @model_validator(mode="after")
    def _complete(self):
        if self.answerable and not (self.sources and self.facts):
            raise ValueError(f"{self.id}: an answerable case needs its sources and its facts")
        if not self.answerable and (self.sources or self.facts):
            raise ValueError(f"{self.id}: an unanswerable case has no sources and no facts")
        return self


class Reply(BaseModel):
    """The part of the reply of /api/ask that the evaluation reads."""
    answer: str
    sources: list[str]
    steps: list[dict] = []
    finished_by: str = ""
    model: str = ""
    seconds: float = 0


class Verdict(BaseModel):
    """What the judge must reply. The schema goes to the model, and pydantic checks the reply."""
    says_not_covered: bool = Field(
        description="True if the answer says the documentation does not cover the question or a part of it"
    )
    reason: str = Field(description="One short sentence")


class Result(BaseModel):
    id: str
    answerable: bool
    passed: bool
    retrieved: bool | None = None
    cited: bool | None = None
    facts_found: int = 0
    facts_total: int = 0
    says_not_covered: bool | None = None
    finished_by: str = ""
    steps: int = 0
    seconds: float = 0
    error: str = ""
    # what the agent said, to read why a case failed
    answer: str = ""
    sources: list[str] = []


class Report(BaseModel):
    model: str
    cases: int
    pass_rate: float
    retrieval: float = Field(description="Share of answerable cases whose right section was read")
    citation: float = Field(description="Share of answerable cases whose answer cites a right section")
    facts: float = Field(description="Share of all the facts of answerable cases found in the answers")
    abstention: float = Field(description="Share of unanswerable cases where the agent said it does not know")
    finished_by: dict[str, int]
    mean_seconds: float
    results: list[Result]


def load_cases(path: Path = CASES) -> list[Case]:
    cases = [Case(**raw) for raw in json.loads(path.read_text(encoding="utf-8"))]
    duplicated = [id for id, n in Counter(case.id for case in cases).items() if n > 1]
    if duplicated:
        raise ValueError(f"duplicated case ids: {duplicated}")
    return cases


def _plain(text: str) -> str:
    """Lowercase, one space between words, one kind of slash: `local\\compose.yaml` = `local/compose.yaml`."""
    return re.sub(r"\s+", " ", text.lower().replace("\\", "/"))


def has_fact(answer: str, spellings: list[str]) -> bool:
    plain = _plain(answer)
    return any(_plain(spelling) in plain for spelling in spellings)


def cited_sources(answer: str, sources: list[str]) -> set[str]:
    """The sources the answer cites: [2] is the second source, [1][3] and [1, 3] cite two."""
    numbers = {int(n) for group in re.findall(r"\[([\d,\s]+)\]", answer) for n in re.findall(r"\d+", group)}
    return {sources[n - 1] for n in numbers if 1 <= n <= len(sources)}


def score(case: Case, reply: Reply, verdict: Verdict | None) -> Result:
    result = Result(
        id=case.id, answerable=case.answerable, passed=False, finished_by=reply.finished_by,
        steps=len(reply.steps), seconds=reply.seconds, answer=reply.answer, sources=reply.sources,
        says_not_covered=verdict.says_not_covered if verdict else None,
    )
    if not case.answerable:
        result.passed = bool(verdict and verdict.says_not_covered)
        return result
    right = set(case.sources)
    result.retrieved = bool(right & set(reply.sources))
    result.cited = bool(right & cited_sources(reply.answer, reply.sources))
    result.facts_total = len(case.facts)
    result.facts_found = sum(has_fact(reply.answer, spellings) for spellings in case.facts)
    result.passed = result.retrieved and result.cited and result.facts_found == result.facts_total
    return result


def report(model: str, results: list[Result]) -> Report:
    answerable = [r for r in results if r.answerable and not r.error]
    unanswerable = [r for r in results if not r.answerable and not r.error]

    def share(items, test):
        return round(sum(1 for item in items if test(item)) / len(items), 3) if items else 0.0

    facts_total = sum(r.facts_total for r in answerable)
    return Report(
        model=model,
        cases=len(results),
        pass_rate=share(results, lambda r: r.passed),
        retrieval=share(answerable, lambda r: r.retrieved),
        citation=share(answerable, lambda r: r.cited),
        facts=round(sum(r.facts_found for r in answerable) / facts_total, 3) if facts_total else 0.0,
        abstention=share(unanswerable, lambda r: r.says_not_covered),
        finished_by=dict(Counter(r.finished_by for r in results if not r.error)),
        mean_seconds=round(sum(r.seconds for r in results) / len(results), 1) if results else 0.0,
        results=results,
    )


JUDGE = (
    "You check an answer given by an assistant about the documentation of a software project. "
    "Decide only one thing: does the answer say that the documentation does not cover the question, "
    "or a part of it? An answer that explains how to do it, even if it is wrong, does not say so."
)


def judge(ollama: str, model: str, case: Case, reply: Reply) -> Verdict:
    """Ask the LLM judge. Ollama constrains the reply to the JSON schema; pydantic validates it."""
    response = httpx2.post(
        f"{ollama}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": JUDGE},
                {"role": "user", "content": f"Question: {case.question}\n\nAnswer:\n{reply.answer}"},
            ],
            "format": Verdict.model_json_schema(),
            "stream": False,
            "think": False,
            "options": {"temperature": 0, "num_predict": 120},
        },
        timeout=180,
    )
    response.raise_for_status()
    return Verdict.model_validate_json(response.json()["message"]["content"])


def run(url: str, ollama: str, judge_model: str | None, cases: list[Case]) -> Report:
    results, model = [], ""
    for number, case in enumerate(cases, 1):
        started = time.perf_counter()
        try:
            response = httpx2.post(f"{url}/api/ask", json={"question": case.question}, timeout=900)
            response.raise_for_status()
            reply = Reply.model_validate(response.json())
            model = reply.model or model
            # the judge is needed only where the plain checks cannot decide
            verdict = None if case.answerable else judge(ollama, judge_model or reply.model, case, reply)
            result = score(case, reply, verdict)
        except (httpx2.HTTPError, ValidationError, KeyError) as exc:
            result = Result(id=case.id, answerable=case.answerable, passed=False,
                            seconds=round(time.perf_counter() - started, 1), error=str(exc)[:200])
        results.append(result)
        mark = "PASS" if result.passed else "FAIL"
        print(f"{number:2}/{len(cases)} {mark} {case.id:22} {result.seconds:6.1f} s  {result.error}", flush=True)
    return report(model, results)


def push(gateway: str, result: Report):
    """Hand the scores to the Pushgateway, where Prometheus reads them like any other target."""
    registry = CollectorRegistry()
    scores = Gauge("eval_score", "Scores of the last evaluation, 0 to 1", ["model", "score"], registry=registry)
    for name in ("pass_rate", "retrieval", "citation", "facts", "abstention"):
        scores.labels(result.model, name).set(getattr(result, name))
    Gauge("eval_mean_seconds", "Mean time of a question in the last evaluation", ["model"],
          registry=registry).labels(result.model).set(result.mean_seconds)
    Gauge("eval_cases", "Questions in the last evaluation", ["model"], registry=registry).labels(result.model).set(result.cases)
    Gauge("eval_last_run_timestamp_seconds", "When the last evaluation ended", registry=registry).set_to_current_time()
    push_to_gateway(gateway, job="agent-eval", registry=registry)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://127.0.0.1:8080", help="Address of the agent")
    parser.add_argument("--ollama", default="http://127.0.0.1:11434", help="Ollama, for the judge")
    parser.add_argument("--judge-model", help="Model of the judge (default: the model of the agent)")
    parser.add_argument("--only", nargs="*", help="Ids of the cases to run")
    parser.add_argument("--min-pass", type=float, default=0.0, help="Fail below this pass rate")
    parser.add_argument("--out", type=Path, help="Write the full report here as JSON")
    parser.add_argument("--pushgateway", help="Push the scores to this Prometheus Pushgateway")
    args = parser.parse_args(argv)

    cases = [case for case in load_cases() if not args.only or case.id in args.only]
    result = run(args.url.rstrip("/"), args.ollama.rstrip("/"), args.judge_model, cases)
    if args.out:
        args.out.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    if args.pushgateway:
        push(args.pushgateway, result)

    print(f"\nmodel {result.model}: pass {result.pass_rate:.0%} of {result.cases}, "
          f"retrieval {result.retrieval:.0%}, citation {result.citation:.0%}, facts {result.facts:.0%}, "
          f"abstention {result.abstention:.0%}, {result.mean_seconds} s per question, "
          f"ended by {result.finished_by}")
    if result.pass_rate < args.min_pass:
        print(f"FAILED: pass rate {result.pass_rate:.0%} is under {args.min_pass:.0%}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
