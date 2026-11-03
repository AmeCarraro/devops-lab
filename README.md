# devops-lab

A small agent platform, built to learn how AI workloads are deployed and operated. It runs on Kubernetes with a local LLM and does two things:

- **Fit**: it fits a vision pipeline to a small device. You give a device and two targets, speed and accuracy. A small language model chooses a configuration, a sandbox runs it in a pod that has the CPU and the memory of that device, and the search goes on until the measurements meet the targets.
- **Ask**: it answers questions on its own documentation, searching it step by step and citing the sections it read.

| Part | Where | What it is |
|---|---|---|
| Web page | `web/` | TypeScript and React. An overview, the Fit view with a live chart of the attempts, and the Ask view. |
| Desktop app | `web/src-tauri/` | Rust and Tauri. The same page as a Windows application, plus a native reading of the GPU. |
| Agent | `app/` | Python and FastAPI. Two loops in which a small local model works with tools: one searches the documentation, one fits a pipeline. |
| Docs server | `mcp-server/` | Search by meaning and by name, exposed over the Model Context Protocol. |
| Sandbox server | `sandbox/` | Runs a pipeline as a locked-down Kubernetes Job and measures it, exposed over the Model Context Protocol. |
| Bench image | `bench/` | What a run executes: five vision models in two precisions, 200 evaluation pictures, one script. |
| Measurements | `tools/` | A script that measures every configuration through the sandbox and writes the two pages on the models from the results. |
| Kubernetes | `k8s/`, `local/` | Manifests for the services and the sandbox, and a k3s cluster that runs inside Docker. |
| CI/CD | `.github/workflows/`, `runner/` | GitHub Actions. The deploy job runs on a self-hosted runner inside the cluster. |
| Monitoring | `app/metrics.py`, `k8s/monitoring/` | Prometheus metrics of the API, the LLM and the research runs; Prometheus, Grafana with a dashboard, and alerts, all kept as code. |
| Evaluation | `eval/` | 28 fixed questions scored on retrieval, citations, facts and honest "not covered" (LLM judge with a pydantic schema); a gate in the pipeline and a row in Grafana. |
| AWS | `infra/` | Terraform for a single-node cluster with Ollama on EC2, its state in S3, and CloudWatch alarms. |

## Run it locally

You need Docker Desktop, and Ollama with the models `granite4.1:3b` and `nomic-embed-text`.

```powershell
.\local\deploy.ps1
```

The first run builds the bench image, which takes about ten minutes. Then open http://127.0.0.1:8080/, and the Grafana dashboard at http://grafana.localhost:8080/d/devops-lab-agent.

## Documentation

- [Architecture](docs/architecture.md)
- [Model zoo](docs/model-zoo.md): how fast, accurate and large each model is
- [Fitting guide](docs/fitting-guide.md): what each setting does and what to change when a target is missed
- [Local development](docs/local-development.md)
- [Pipeline and AWS](docs/deployment.md), with the current status of both
- [Monitoring](docs/monitoring.md): the metrics, the dashboard and the alerts
- [Evaluation](docs/evaluation.md): how good the answers are, as a number the pipeline checks
- [Troubleshooting](docs/troubleshooting.md)

These pages are also what the agent reads: it answers questions from them, and it looks up the models and the settings in them before it chooses a configuration.

## The pictures

The models are measured on 200 pictures from [Imagenette](https://github.com/fastai/imagenette), a subset of ImageNet published by fast.ai. They are downloaded when the bench image is built and are not part of this repository.
