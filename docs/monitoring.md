# Monitoring

The agent measures itself, Prometheus collects the measurements, Grafana shows them and Alertmanager lists the alerts that fire. The same setup runs on the local cluster and on the EC2 node. On EC2, CloudWatch also watches the node from outside.

## What runs

One Helm chart, kube-prometheus-stack, installs everything in the namespace `monitoring`. Its version is in `k8s/monitoring/VERSION` and its settings are in `k8s/monitoring/values.yaml`.

- **Prometheus** reads the metrics of every target every 15 seconds and keeps them for 3 days.
- **Alertmanager** receives the alerts that fire. No receiver is configured: the alerts are visible in its page and in Grafana, and they are not sent anywhere.
- **Grafana** shows the dashboards. The data source is Prometheus.
- **node-exporter** measures the node: CPU, memory, disk, network.
- **kube-state-metrics** measures the Kubernetes objects: pods, restarts, rollouts.
- The **Prometheus Operator** turns the resources `ServiceMonitor` and `PrometheusRule` into the configuration of Prometheus.
- The **Pushgateway**, a second chart (`k8s/monitoring/pushgateway/`), keeps the scores of the last [evaluation](evaluation.md). The evaluation is a batch job that ends before Prometheus could read it, so it pushes its numbers there.

k3s runs the scheduler, the controller manager and the proxy inside a single process, and keeps its state in SQLite instead of etcd. These components have no endpoint of their own, so the values turn off their scraping and their default alerts. Left on, their targets would be down forever and their alerts would always fire.

## Open it

On the local cluster, after `.\local\deploy.ps1`:

- Grafana: http://grafana.localhost:8080/d/devops-lab-agent
- Prometheus: http://prometheus.localhost:8080, and its list of alerts at http://prometheus.localhost:8080/alerts
- Alertmanager: http://alertmanager.localhost:8080

The browser resolves every `*.localhost` name to the PC itself, and Traefik routes each name to its service. The ingress of the cluster listens only on 127.0.0.1, so nobody else reaches these pages.

On EC2 nothing of this is exposed. Open an SSH tunnel and use port 8081, because 8080 belongs to the local cluster:

```powershell
ssh -i ~/.ssh/devops-lab -N -L 8081:127.0.0.1:80 ubuntu@<public_ip>
```

Then open http://grafana.localhost:8081/d/devops-lab-agent. `.\tf.ps1 cluster output grafana_tunnel` prints the command with the right address.

Anyone who reaches Grafana can look at the dashboards. Changing them needs the admin login. The admin password is made at the first deploy and is kept only in the Secret `grafana-admin`:

```powershell
kubectl -n monitoring get secret grafana-admin -o jsonpath="{.data.admin-password}"
```

The value is in base64.

## What the agent measures

The metrics are defined in `app/metrics.py` and served at `GET /metrics` of the agent. The path is outside `/api`, so the ingress does not route it: only Prometheus, inside the cluster, reads it. Every metric is a counter or a histogram. Rates, error ratios and percentiles are computed by Prometheus, not by the agent.

| Metric | Type | Labels | What it answers |
|---|---|---|---|
| `http_requests_total` | counter | method, route, status | How many requests, and how many failed |
| `http_request_duration_seconds` | histogram | method, route | How long until the response starts |
| `llm_requests_total` | counter | model, mode, outcome | How many calls to the LLM, and how many failed |
| `llm_request_duration_seconds` | histogram | model, mode | How long a call to the LLM takes |
| `llm_tokens_total` | counter | model, mode, kind | How many tokens the LLM read (`prompt`) and wrote (`completion`) |
| `llm_time_to_first_token_seconds` | histogram | model | How long the user waits before the answer starts to appear |
| `agent_runs_total` | counter | finished_by | How the research runs ended |
| `agent_run_duration_seconds` | histogram | | How long a run takes, from the question to the last word of the answer |
| `agent_run_steps` | histogram | | How many tool calls a run needed |
| `agent_run_excerpts` | histogram | | How many excerpts of documentation a run collected |
| `agent_tool_calls_total` | counter | tool, result | What the tool calls of the model led to |
| `agent_tool_call_duration_seconds` | histogram | tool, outcome | How long a call to an MCP tool takes |

The three groups follow three questions.

- **Is the API healthy?** The RED method: the rate of requests, the errors, the duration. The label `route` is the template of the route, such as `/api/ask`, never the raw path. A path that matches no route is counted as `unmatched`, otherwise every typo or probe of a scanner would create a new series.
- **What does the model cost and how fast is it?** Ollama returns the number of tokens it read and wrote with every reply, and the agent adds them up. The `mode` of a call is `tools` for a step of the research loop, `structured` for the detection of the language of the question and `stream` for the answer.
- **Does the search work?** A run is counted by how it ended: `finish` (the model was convinced), `answer` (it started answering inside the loop), `max_steps` (it ran out of steps), `error` or `cancelled` (the client closed the connection). A run that collected no excerpt lands in the bucket `le="0.0"` of `agent_run_excerpts`: its answer has nothing to stand on, even when the service is up and fast.

The run metrics come from the same events that the web page shows (`metrics.observe_run`), so the dashboard and the page cannot disagree about what a run did.

A series with labels appears when it is first used, already at 1. `rate()` and `increase()` need two samples, so that first event would be lost, and a panel would stay empty until the second one. The series whose labels are known in advance, the endings of a run and the modes and outcomes of the model, are created at zero when the agent starts (`metrics.prepare`).

For the streaming routes, `http_request_duration_seconds` measures the time until the stream opens, a few milliseconds. The time of the whole answer is `agent_run_duration_seconds`.

The tool name of `agent_tool_calls_total` comes from the model. It is cut to 40 characters, but a model that invented many names would still add a series for each of them.

## The dashboard

The dashboard is `k8s/monitoring/dashboards/agent.json`. The deploy puts it in the ConfigMap `dashboard-agent` with the label `grafana_dashboard=1`. A sidecar container of Grafana watches for ConfigMaps with that label in every namespace and loads them. A change to the file reaches Grafana with the next deploy, without a click.

It has six rows:

1. **At a glance**: questions in the last hour, the share of API errors, the answer time that 95% of the runs stay under, the wait for the first token, the share of searches that found nothing, the replicas up.
2. **API**: requests, errors and time to first byte, by route.
3. **LLM**: duration of the calls, tokens per second, time to first token, calls by outcome, prompt tokens per call.
4. **Agent and search**: runs by how they ended, run duration, steps and excerpts per run, tool calls by result, duration of the MCP tools.
5. **Resources**: CPU and memory of the pods of the agent and of the docs server.
6. **Evaluation**: the scores of the last evaluation and how they changed, from the Pushgateway.

The kube-prometheus-stack chart also installs its own dashboards, for the node, the pods and the namespaces.

## The alerts

The alerts are in `k8s/monitoring/alerts.yaml`. Prometheus evaluates them every 15 seconds. `for` is how long the condition must hold before the alert fires, so that a single slow answer or a restart does not page anyone.

| Alert | Fires when | For |
|---|---|---|
| `AgentDown` | a replica of the agent does not answer on `/metrics` | 2 minutes |
| `AgentErrors` | more than 5% of the requests to `/api` answer 5xx | 5 minutes |
| `LLMCallsFail` | calls to the LLM fail: Ollama down, model missing, or a call longer than 180 seconds | 5 minutes |
| `AnswersSlow` | 95% of the runs take longer than 2 minutes | 10 minutes |
| `SearchFindsNothing` | a quarter of the runs of the last hour found no documentation, with at least 4 runs | at once |

`SearchFindsNothing` is about quality, not infrastructure: the service is up and fast, but the answers have nothing to stand on.

On the EC2 node the model runs on the CPU, and `AnswersSlow` is expected to fire. That is the measurement that says the model needs a GPU or a managed service.

## How it is deployed

The stack and the configuration of the app are deployed apart.

- **The stack** is installed once per cluster, by the cluster admin, like the runner controller. `local\deploy.ps1` installs it on the local cluster and `infra\cluster\deploy.ps1` on EC2. Both run `helm upgrade --install`, so a later run upgrades it in place.
- **What to scrape, what to alert on, and the dashboard** travel with the app: the pipeline and both deploy scripts apply `k8s/monitoring/servicemonitor.yaml`, `k8s/monitoring/alerts.yaml` and the dashboard together with the Deployments. The service account `deployer` of the pipeline may write `ServiceMonitor` and `PrometheusRule` in the namespace `demo` and nothing else of the stack (`k8s/bootstrap/rbac.yaml`).

The ServiceMonitor selects the Service `demo-api` by its label `app: demo-api` and reads the port named `http`. Prometheus finds the pods through the Service, so a new replica is read as soon as it is ready.

## Add a metric

1. Define it in `app/metrics.py`, as a counter or a histogram, with labels that take few values.
2. Record it where it happens, in the agent.
3. Add a test in `tests/test_metrics.py`.
4. Add a panel to `k8s/monitoring/dashboards/agent.json`, and an alert to `k8s/monitoring/alerts.yaml` if someone should act on it.

## Limits

- Prometheus keeps its data in the pod, without a volume: a new Prometheus pod starts empty.
- Prometheus and Alertmanager have no login. They are reachable only from the PC, or through the tunnel on EC2.
- The docs server and the web page have no metrics of their own yet. The agent times every call to the docs server, and the Resources row shows the CPU and memory of the docs server next to the agent's.
