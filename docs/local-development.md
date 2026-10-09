# Local development

Everything runs on the PC and costs nothing: a k3s cluster inside a Docker container, and Ollama on the host for the models.

## Prerequisites

- Docker Desktop is running.
- Ollama is running on the host with the two models:

```powershell
ollama pull granite4.1:3b
ollama pull nomic-embed-text
```

## Deploy

```powershell
.\local\deploy.ps1
```

The script does by hand what the pipeline does in CI:

1. starts the k3s container and waits for the node to be Ready;
2. builds the three images (agent, docs-mcp and web) with a timestamp as tag;
3. copies the images into the node, because there is no registry locally;
4. writes the ConfigMap `llm-config` with the address of Ollama and the model names;
5. applies the manifests in `k8s/` and waits for the rollout.

## Change the chat model

Download the model with Ollama, then pass its name to the deploy script:

```powershell
ollama pull qwen3:4b
.\local\deploy.ps1 -ChatModel qwen3:4b
```

The script writes the name into the ConfigMap `llm-config` as `CHAT_MODEL` and the agent uses it from the next rollout. The model must support tool calling. The embedding model is changed the same way with `-EmbedModel`.

## Ask a question

Open the page at http://127.0.0.1:8080/ and type the question. The page shows the steps of the agent, the answer and the sections it read. The Stop button interrupts a run.

The same from the command line, without the page:

```powershell
Invoke-RestMethod http://127.0.0.1:8080/api/ask -Method Post -ContentType 'application/json' -Body '{"question": "How do I stop the cluster?"}'
```

The interactive API page is at http://127.0.0.1:8080/api/docs.

## Work on the web page

Node.js is not installed on the PC: `npm.ps1` runs npm in a container, inside `web/`.

```powershell
.\npm.ps1 install
.\npm.ps1 test
.\npm.ps1 run dev
```

`run dev` serves the page on http://127.0.0.1:5173 and reloads it when a file in `web/src` changes. The API still comes from the local cluster, so the cluster must be running.

## Work on the desktop app

Rust is not installed on the PC: `cargo.ps1` runs cargo in a container, inside `web/src-tauri`.

```powershell
.\cargo.ps1 test
.\cargo.ps1 clippy
```

The first run builds the container image and compiles Tauri, which takes several minutes. Later runs take seconds. This checks and tests the native code on Linux. The Windows application is built on GitHub by the workflow `desktop`, because a window cannot be opened from a container.

To run the app with live reload, `npm run tauri dev`, Rust and the Microsoft C++ build tools must be installed on the PC.

## Use the MCP server from another client

The MCP endpoint is http://127.0.0.1:8080/mcp, with the Streamable HTTP transport. Any MCP client can connect to it: give the client this address and it discovers the two search tools by itself.

## Look inside the cluster

```powershell
$env:KUBECONFIG = "local\kubeconfig\kubeconfig.yaml"
kubectl -n demo get pods
kubectl -n demo logs deploy/demo-api
kubectl -n demo logs deploy/docs-mcp
```

## Stop the cluster

```powershell
docker compose -f local\compose.yaml stop
```

Stopping keeps all the data, which lives in the Docker volume `devops-lab_k3s-data`. Run `.\local\deploy.ps1` to start again.

## Delete the cluster

```powershell
docker compose -f local\compose.yaml down -v
```

This removes the container and the volume. The next deploy creates a new empty cluster.

## Run the tests

```powershell
pip install -r requirements-dev.txt
pytest
```

The tests do not need Ollama: the LLM is replaced by a scripted fake. The tests of the web page run with `.\npm.ps1 test`.

## Change the documentation

Add or edit markdown files in `docs/`, then run `.\local\deploy.ps1` again. The new docs-mcp image contains the new files and the index is rebuilt at the first question.
