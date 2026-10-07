# Troubleshooting

## /api/ask returns 502

The agent could not reach the LLM or the MCP server. The `detail` field of the error says which call failed. In the web page the same failure appears in red under the question. Read the agent log first:

```powershell
kubectl -n demo logs deploy/demo-api
```

Common causes:

- Ollama is not running on the host. Start it and check with `ollama ps`.
- The model named in the ConfigMap is not downloaded. Ollama answers 404; fix it with `ollama pull <model>`.
- The docs-mcp pod is not ready. Check with `kubectl -n demo get pods`.

## Pods cannot resolve host.docker.internal

This is expected. Inside a pod the DNS server is CoreDNS, which does not know the internal names of Docker, so `host.docker.internal` only resolves on the node. `local\deploy.ps1` resolves the name on the node and writes the IP address of the host into the ConfigMap `llm-config`. To see the value in use:

```powershell
kubectl -n demo get configmap llm-config -o yaml
```

## Answers are slow

The first question after a start is slower, because Ollama loads the chat model into the GPU memory and docs-mcp builds the index. Later questions take about 5 seconds: every step of the research loop is one call to the model, and a question takes from 3 to 6 steps plus the answer.

If every question is slow, run `ollama ps`. The chat model must show `100% GPU` and the embedding model `100% CPU`. docs-mcp asks for embeddings on the CPU on purpose: with only 4 GB of video memory, Ollama would unload the chat model to load the embedding model, and reload it at every question.

If the chat model shows a CPU/GPU split, the video memory is full: close other programs that use the GPU or lower `NUM_CTX`.

## The answer is wrong or invents details

The chat model is very small. Look at `steps` and `sources` in the reply to see what was searched and what was retrieved. If the right section is in `sources`, the research worked and the model wrote a bad answer. If it is not there, the queries or the chunking are the problem.

The weak point is the decision to stop. The model can call `finish` with nothing missing while the excerpts do not really answer the question. `finished_by` in the reply tells how the loop ended.

## The model does not call the tools

When tool calling fails, the `steps` list in the reply is empty and the answer says that nothing was found. The model is not reliable enough at tool calling: `llama3.2:3b` behaves this way. Use a model that supports tools well, for example `granite4.1:3b`.

## MCP client gets 421 Invalid Host header

The MCP server rejects requests whose `Host` header is not in its allow list. This protects against DNS rebinding attacks. The default list accepts `docs-mcp:8001`, `127.0.0.1` and `localhost` on any port. To reach the server under another name, set the environment variable `ALLOWED_HOSTS` of docs-mcp to a comma-separated list of `host:port` values.

## Pod stuck in ImagePullBackOff on the local cluster

The image is not in the node. Local images are never pulled from a registry: `local\deploy.ps1` copies them into the node. Run the script again. To list the images in the node:

```powershell
docker exec devops-lab-k3s ctr -n k8s.io images ls -q
```

## Port 8080 or 6443 is already in use

Another program uses the port. Change the left side of the port mapping in `local\compose.yaml`, for example `127.0.0.1:8081:80`.
