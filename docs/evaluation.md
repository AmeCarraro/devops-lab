# Evaluation

The evaluation says whether the agent answers well, with a number that can be compared before and after a change. It asks fixed questions to a running agent, scores every answer, and fails the pipeline when too few pass.

## What it checks

The questions are in `eval/cases.json`. There are two kinds.

- **Answerable**: the documentation answers it. The case names the sections that hold the answer and the facts the answer must contain: a command, a name, a number. Each fact lists the spellings that count.
- **Unanswerable**: nothing in the documentation answers it. The right answer says so instead of guessing.

An answerable question passes when all three checks pass. They are plain code, so they are free and always give the same result:

| Check | Passes when |
|---|---|
| retrieved | one of the right sections is among the `sources` the research read |
| cited | the answer cites one of the right sections by its number, like `[2]` |
| facts | every fact appears in the answer, ignoring case, spaces and the kind of slash |

An unanswerable question passes when the answer says that the documentation does not cover it. Code cannot decide that, so an LLM judge does. Its reply is forced into a JSON schema made from the pydantic model `Verdict`, and pydantic validates it: a judge that answers anything else counts as an error, never as a pass.

The two checks on the sources tell apart the two ways an answer goes wrong. When the right section was read but not cited, the research worked and the writing of the answer failed. When it was not read, the search is the problem.

## The scores

| Score | What it is |
|---|---|
| `pass_rate` | share of all the questions that passed |
| `retrieval` | share of the answerable questions whose right section was read |
| `citation` | share of the answerable questions whose answer cites a right section |
| `facts` | share of the expected facts found in the answers |
| `abstention` | share of the unanswerable questions where the agent said it does not know |

The report also counts how the research runs ended (`finished_by`) and the mean time of a question.

## Run it

Against the local cluster, with the model on the PC:

```powershell
python eval\evaluate.py --url http://127.0.0.1:8080 --pushgateway http://pushgateway.localhost:8080 --out eval-report.json
```

It needs `httpx2`, `prometheus-client` and `pydantic`, which are in `requirements-dev.txt`. `--only` runs some questions by id. `--min-pass 0.6` makes the exit code 1 when fewer than 60% pass.

## In the pipeline

The job `eval` of `.github/workflows/ci.yml` runs after the deploy, on the runner inside the cluster, against the version just deployed and the real model. It fails when the pass rate is under the repository variable `EVAL_MIN_PASS`, 0.65 by default. The full report is kept as the artifact `eval-report` of the run, and the summary of the run shows the scores.

The unit tests of the evaluation, `tests/test_evaluate.py`, run with the other tests at every push. They also check that every section named in `cases.json` still exists, so that renaming a heading cannot silently turn right answers into failures.

## In Grafana

The evaluation is a batch job: it ends before Prometheus could read it. It pushes its scores to the Pushgateway, which keeps the last ones and is read by Prometheus like any other target. The row "Evaluation" of the dashboard shows the last scores and how they changed over time. The Pushgateway has no volume: after a restart it is empty until the next evaluation.

## Results

Measured on 2026-11-03 on the local cluster, with `granite4.1:3b` on the GPU of the PC and the same model as judge:

| Run | Prompt of the answer | pass | retrieval | citation | facts | abstention |
|---|---|---|---|---|---|---|
| 1 | as in `app/agent.py` | 71% | 96% | 71% | 93% | 75% |
| 2 | "end every sentence with the number of its excerpt" | 29% | 96% | 71% | 22% | 75% |
| 3 | back as in run 1 | 71% | 96% | 71% | 93% | 75% |

- The search works: the right section is read for 23 of the 24 answerable questions. The weak part is the writing of the answer, which cites the wrong excerpt or none in 7 of them.
- Runs 1 and 3 gave the same result for every question: with temperature 0 the evaluation repeats itself, so a change of one question is a change of the agent, not noise.
- Run 2 is a prompt change meant to fix the citations. The small model answered `[1]` and nothing else. The gate of the pipeline, at 65%, would have stopped it.
- A question takes about 9 seconds, so the whole evaluation takes about 4 minutes.

## Add a question

1. Add a case to `eval/cases.json` with a new `id`. Copy the sources from the anchors of the headings, as the agent reports them: `docs/<file>.md#<heading-in-lowercase-with-dashes>`.
2. Write facts that a right answer cannot avoid, and that a wrong one is unlikely to contain by chance.
3. Run `pytest` to check the case, then the evaluation against the local cluster.

Questions about the documentation must not be added to `docs/`: the agent would find the question itself instead of the answer.
