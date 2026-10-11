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

## A run fails with out_of_memory

This is a result, not a fault. The pipeline needed more memory than the device has, and Kubernetes stopped it. The page shows the attempt in red, and the model is told to try a smaller model or int8. The page on the model zoo lists how much memory each model needs.

To see it from the side of Kubernetes, look at the pod of the run within five minutes: its status is `OOMKilled`.

```powershell
kubectl -n sandbox get pods
```

## A run stays in "Waiting for a pod"

The Job exists and Kubernetes has not created its pod. The usual cause is the quota of the sandbox: at most 2 pods at a time, 4 CPU cores and 2 GB of memory in all. A third search started at the same moment waits for one of the others. The events of the namespace say what is refused:

```powershell
kubectl -n sandbox get events --sort-by=.lastTimestamp
```

## A run fails because the bench image is not on the node

The run reports `The bench image is not on the node`. A run never downloads its image: the node must already have it. Locally, run `local\deploy.ps1` again, which loads the image named in `bench\VERSION`. After a deploy by the pipeline, check that the Deployment `sandbox-mcp` finished its rollout: its init container is what makes the node download the image.

## A search ends with "Kubernetes refused the run"

The sandbox server asked Kubernetes for a Job and was turned down. The message carries the reason given by Kubernetes. `forbidden` means that the namespace `sandbox` or the role of the service account `sandbox-mcp` is missing: apply `k8s\bootstrap\sandbox.yaml` as a cluster admin. `exceeded quota` means the device asked for is larger than the quota of the sandbox.

## A search finds nothing that fits

Read the attempts in the page. Three things can be happening.

- The targets cannot be met on that device. The tables of the model zoo show what each configuration reaches on one core: no configuration is above 87.5% accuracy, and the accurate models are slow.
- The model wastes runs. A small model sometimes changes the wrong setting or tries a configuration that the documentation warns against. Start the search again, or use a larger chat model.
- A run was disturbed. Speed is measured on a PC that does other things too: a configuration close to the target can pass once and miss once.

## The speeds change from one run to the next

The device is simulated with CPU limits on the PC, and the PC is shared with everything else that runs on it: Ollama, the browser, a build. A heavy program that starts during a run makes that run slower. Compare configurations measured in the same conditions, and repeat a run that matters. Accuracy does not change: the same configuration always gives the same answers on the same pictures.

How large the effect is was checked once, on 2026-10-10: the 40 configurations of the reference device were measured twice. The accuracy was identical in all 40. The speed differed by about 2% for a typical configuration. Four runs that overlapped with a program using many cores were between 30% and 50% slower.

## MCP client gets 421 Invalid Host header

The MCP server rejects requests whose `Host` header is not in its allow list. This protects against DNS rebinding attacks. The default list accepts `docs-mcp:8001`, `127.0.0.1` and `localhost` on any port. To reach the server under another name, set the environment variable `ALLOWED_HOSTS` of docs-mcp to a comma-separated list of `host:port` values. The sandbox server works the same way, with `sandbox-mcp:8002` in its default list.

## Reach the sandbox server from the PC

No ingress route leads to the sandbox server, on purpose: whoever reaches it can start runs. To call its tools from the PC while developing, open a tunnel through the Kubernetes API, which asks for the admin credentials of the cluster:

```powershell
kubectl -n demo port-forward svc/sandbox-mcp 8002:8002
```

The MCP endpoint is then http://127.0.0.1:8002/mcp until the command is stopped.

## Pod stuck in ImagePullBackOff on the local cluster

The image is not in the node. Local images are never pulled from a registry: `local\deploy.ps1` copies them into the node. Run the script again. To list the images in the node:

```powershell
docker exec devops-lab-k3s ctr -n k8s.io images ls -q
```

## Port 8080 or 6443 is already in use

Another program uses the port. Change the left side of the port mapping in `local\compose.yaml`, for example `127.0.0.1:8081:80`.
