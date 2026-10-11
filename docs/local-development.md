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
2. builds the images (agent, docs-mcp, sandbox-mcp and web) with a timestamp as tag;
3. copies the images into the node, because there is no registry locally;
4. writes the ConfigMap `llm-config` with the address of Ollama and the model names;
5. applies the manifests in `k8s/`, the sandbox namespace included, and waits for the rollout.

## The bench image

The bench image is what a run in the sandbox executes: five vision models, each as fp32 and int8, and 200 evaluation pictures. The deploy script builds it only when the number in `bench\VERSION` is new, and loads it into the node only when the node does not have it.

The first build takes about ten minutes. It downloads PyTorch, the weights of the models and the Imagenette pictures, about 700 MB in all, exports the models to ONNX and quantizes them. Nothing of this is installed on the PC: it happens inside the build, and only the result is kept.

After a change to a file in `bench/`, raise the number in `bench\VERSION` and run the deploy script.

To run one pipeline by hand, without the cluster and with the limits of a device:

```powershell
docker run --rm --cpus 1 --memory 512m devops-lab-bench:2 '{\"model\": \"resnet18\", \"precision\": \"int8\", \"input_size\": 224, \"threads\": 1}'
```

The last line it prints is `RESULT` followed by the measurements.

## Measure the zoo again

The pages on the model zoo and the fitting guide are not written by hand. `tools\zoo_report.py` runs every configuration through the sandbox, saves the results in `tools\measurements.json` and writes the two pages from them, numbers and advice included. Do it again after a change to the models, or on another machine.

```powershell
kubectl -n demo port-forward svc/sandbox-mcp 8002:8002
```

In another terminal, with the PC doing nothing else, because the speeds are measured on it:

```powershell
Remove-Item tools\measurements.json
python tools\zoo_report.py measure
python tools\zoo_report.py write
.\local\deploy.ps1
```

The first command takes about ten minutes. The last one puts the new pages in front of the agent.

## Fit a pipeline to a device

Open http://127.0.0.1:8080/#/fit, choose a device and two targets, and start. Every attempt appears with the reason the model gave, its measurements and a mark on the chart.

The same from the command line. The reply is one JSON object per line, as the search goes on:

```powershell
curl.exe -N http://127.0.0.1:8080/api/fit/stream -H "Content-Type: application/json" -d '{\"device\": {\"cpu\": 1, \"memory_mb\": 512}, \"targets\": {\"min_fps\": 30, \"min_accuracy\": 85}}'
```

To watch the runs from the side of Kubernetes while a search is going on:

```powershell
kubectl -n sandbox get jobs,pods --watch
```

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

`run dev` serves the page on http://127.0.0.1:5173 and reloads it when a file in `web/src` changes. The API and the sample pictures still come from the local cluster, so the cluster must be running.

The page is made of one file per view in `web/src`: `Home.tsx`, `Fit.tsx` and `Ask.tsx`, each with a stylesheet of the same name. `index.css` holds the colors, the frame and the pieces they share. `fit.ts` holds the logic of the Fit view that is not drawing, and has its own tests.

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
kubectl -n demo logs deploy/sandbox-mcp
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

The tests need neither Ollama nor a cluster: the LLM is replaced by a scripted fake, and the sandbox by a fake that answers from a table. The tests of the web page run with `.\npm.ps1 test`.

## Change the documentation

Add or edit markdown files in `docs/`, then run `.\local\deploy.ps1` again. The new docs-mcp image contains the new files and the index is rebuilt at the first question.
