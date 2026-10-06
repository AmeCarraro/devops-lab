# devops-lab

A small agent platform, built to learn how AI workloads are deployed and operated: a documentation assistant that runs on Kubernetes and uses a local LLM.

| Part | Where | What it is |
|---|---|---|
| Agent | `app/` | FastAPI service. A small local model searches the documentation in a research loop of tool calls, then answers with its sources. |
| MCP server | `mcp-server/` | Search by meaning and by name, exposed over the Model Context Protocol. |
| Kubernetes | `k8s/`, `local/` | Manifests for both services and a k3s cluster that runs inside Docker. |
| CI/CD | `.github/workflows/`, `runner/` | GitHub Actions. The deploy job runs on a self-hosted runner inside the cluster. |
| AWS | `infra/` | Terraform for a single-node cluster and a cost budget. |

## Run it locally

You need Docker Desktop, and Ollama with the models `granite4.1:3b` and `nomic-embed-text`.

```powershell
.\local\deploy.ps1
```

Then open http://127.0.0.1:8080/docs and try `POST /ask`.

## Documentation

- [Architecture](docs/architecture.md)
- [Local development](docs/local-development.md)
- [Pipeline and AWS](docs/deployment.md), with the current status of both
- [Troubleshooting](docs/troubleshooting.md)

These pages are also the corpus the assistant answers from.
