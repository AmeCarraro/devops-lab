# Architecture

devops-lab is a small agent platform that runs on Kubernetes and talks to a local LLM. It does two things. It answers questions on its own documentation. And it fits a vision pipeline to a small device: it tries configurations in a sandbox, measures them, and stops when one meets the targets.

## Components

- **web** (`web/`): the page a person uses, written in TypeScript with React. It has three views: an overview, Fit and Ask. In Kubernetes it is the Deployment `web`: an nginx container that serves the built files.
- **agent** (`app/`): a FastAPI service, written in Python. It runs the two loops in which the LLM works with tools: the search of the documentation (`app/agent.py`) and the fit of a pipeline (`app/fit.py`). In Kubernetes it is the Deployment `demo-api`, with 2 replicas.
- **docs-mcp** (`mcp-server/`): an MCP server with two tools, `search_docs` and `search_by_name`. It splits the markdown files of `docs/` into chunks, one per section. In Kubernetes it is the Deployment `docs-mcp`, listening on port 8001 at the path `/mcp`.
- **sandbox-mcp** (`sandbox/`): an MCP server that runs a pipeline on a simulated device and measures it. Every run is a Kubernetes Job in the namespace `sandbox`. In Kubernetes it is the Deployment `sandbox-mcp`, on port 8002. No ingress route leads to it.
- **bench** (`bench/`): the image that a run executes. It holds the models, the evaluation pictures and one script, `bench.py`.
- **Ollama**: serves the chat model and the embedding model. Locally it runs on the Windows host, outside the cluster, so that it can use the GPU.
- **Traefik**: the ingress controller that ships with k3s. It routes `/api` to the agent, `/mcp` to docs-mcp and every other path to the web page, so the services share one address.

## Why two languages

The page is TypeScript because a browser only runs JavaScript, and TypeScript is JavaScript with types. The agent is Python because that is where the libraries for models and data are. The two meet in the API: `web/src/api.ts` describes the events of the agent as types, so the compiler checks that the page handles every kind of event.

## The tools

- `search_docs` searches by meaning. It embeds the query with Ollama (`/api/embed`) and returns the chunks closest to it.
- `search_by_name` opens sections by the name of their page or heading. It needs no embeddings. When nothing has that name, it answers with the list of the names that exist.
- `finish` leaves the research loop. It belongs to the agent and not to an MCP server, because it is control flow and not a capability. Its argument `missing` says what the question asks that no excerpt answers yet.
- `run_pipeline` runs one configuration of the pipeline on the device and returns its measurements. It exists only in the fit loop. The agent builds it on top of the sandbox tools `start_run` and `get_run`.

## Request flow of a question

1. A client sends `POST /api/ask` with a question. Traefik forwards it to one of the agent replicas.
2. The agent connects to docs-mcp over MCP (Streamable HTTP). It receives the list of tools and the instructions of the server on how to use them.
3. Research loop, at most 6 steps. In each step the agent calls Ollama (`/api/chat`) with the conversation so far and the tools, and the model calls one tool. The agent executes it and gives the result back to the model.
4. The loop ends when the model calls `finish` with nothing missing, when it starts writing text instead of calling a tool, or when the 6 steps are used up.
5. The agent asks the model which language the question is written in.
6. The agent starts a new conversation that contains only the excerpts collected and the question, and the model writes the answer citing the excerpts like `[1]`.

## Rules of the research loop

The loop is written for a small model, so the agent does not trust it blindly.

- One tool call per step. If the model asks for several at once, only the first is executed.
- A call that was already made is not executed again, even with the words in another order. The model is told to search with different words.
- Excerpts the model has already read are not shown again. A search that finds nothing new says so.
- `finish` is refused until the model has made at least 2 different searches.
- `finish` is refused when its argument `missing` is not empty: the model goes back to search until the steps run out.
- Excerpts stop being added when they fill about half of the context of the model.

## The reply of /api/ask

- `answer`: the text of the answer.
- `sources`: the sections that were read. The number in a citation is the position in this list.
- `steps`: the tool calls of the research loop, in order, with their arguments. `new_excerpts` is the number of excerpts a call added. `refused` says why the agent did not execute a call: `repeated`, `too_early` or `missing`.
- `finished_by`: how the loop ended. `finish` means the model declared it had everything, `answer` means it started writing instead of calling a tool, `max_steps` means it used all 6 steps.
- `model` and `seconds`.

## Fitting a pipeline to a device

A task is a device and two targets: `POST /api/fit/stream` takes the CPU cores and the memory of the device, the minimum speed in images per second and the minimum accuracy.

1. The agent connects to docs-mcp and to sandbox-mcp. The model gets the two search tools and `run_pipeline`.
2. Before the model chooses anything, the agent looks up the documentation the task depends on: the list of the fastest configurations that reach the accuracy asked for, which it opens by the name of its section, and what the device changes if it is smaller or larger than the reference one. What it finds is given to the model with the task.
3. In each step the model calls one tool. It can read more documentation, or run a configuration.
4. For `run_pipeline` the agent calls `start_run` on the sandbox with the configuration of the model and the device of the task, then asks `get_run` every 0.7 seconds until the run is over. Every change of state is sent to the client.
5. The agent compares the measurement with the targets and tells the model which one was missed and by how much. It also looks up the section of the documentation on that problem and gives it to the model with the result.
6. The loop ends at the first configuration that meets both targets, after 8 runs, or after 16 steps.
7. The agent writes the result in words, from the measurements.

## Rules of the fit loop

- The model never declares success. A configuration fits when its measurements say so, and the agent checks that in code.
- The model does not write the result either. The sentence that says which configuration to use is built in code from the measured numbers, because a small model sooner or later gets a number wrong. The words of the model appear only as the reason it gave for each attempt.
- The model is not trusted to find the right page by itself. The agent makes the lookups the task calls for, and the model can add its own.
- The model chooses the pipeline and never the device. The device comes from the task, whatever the model writes.
- The choices the model sees for a pipeline are the ones the sandbox publishes, so they cannot differ from what the sandbox accepts.
- A configuration that was already run is not run again: the model is given the list of what it has run.
- An invalid configuration comes back with the list of the valid values and does not count as a run.
- Text instead of a tool call does not end the search: the model is asked again for a configuration.
- Three steps in a row that achieve nothing end the search: a model that repeats itself would only use up the remaining steps.
- When no attempt fits, the one closest to the targets is reported as such.

## The pod is the device

A run is a Kubernetes Job with one pod. The limits of the pod are the device: `cpu: 500m` and `memory: 256Mi` for a device with half a core and 256 MB. Requests are equal to limits, so the pod gets exactly that much.

Kubernetes enforces the limits like a real device would. A pipeline that uses more CPU than the device has is slowed down, and its speed is measured that way. A pipeline that needs more memory than the device has is killed, and the run is reported as `out_of_memory`.

Using a pod as the device needs no hardware and costs nothing. It does not reproduce the processor of a real board: the numbers say how the configurations compare on the same simulated device, and not how fast they would be on a specific chip.

## What keeps a run inside the sandbox

Everything a run can do is decided outside the code that asks for it, in `k8s/bootstrap/sandbox.yaml` and in the Job that `sandbox/runs.py` builds.

- The namespace `sandbox` enforces the Pod Security Standard `restricted`: Kubernetes refuses a pod that runs as root, asks for privileges or mounts something from the node.
- A NetworkPolicy with no rules denies every connection, in and out. A run cannot reach the internet, the cluster or Ollama.
- The pod gets no service account token, so it has no credentials for the Kubernetes API.
- The root filesystem is read-only and every Linux capability is dropped.
- A Job is stopped after 150 seconds and removed 5 minutes after it ends.
- A ResourceQuota caps the whole namespace at 2 pods, 4 CPU cores and 2 GB of memory.
- The configuration reaches the program as one JSON argument, never through a shell, and only after the sandbox has checked every value against the list of valid choices.

## Who may start a run

Only the service account `sandbox-mcp` may create Jobs in the namespace `sandbox`, and it can do nothing else: create, read and delete Jobs, list pods, read their logs. The sandbox server talks to the Kubernetes API over HTTPS with the token that Kubernetes mounts in its pod (`sandbox/kube.py`).

The sandbox server keeps no state. The name of the Job is the identifier of the run, and every `get_run` reads the Job, its pod and the last lines of its log from Kubernetes.

## The events of /api/fit/stream

One JSON object per line:

- `step`: a look at the documentation, or a call the agent turned down. `by` is `agent` when the agent made the lookup for the model. `refused` is `repeated`, `invalid` or `no_call`.
- `attempt`: the state of a run. It is sent again every time the state changes: `queued`, `starting`, `running` with the pictures measured so far, then `done` with the measurements or `failed` with `out_of_memory`, `timeout` or `error`. `verdict` says which targets the measurement meets.
- `result`: the search is over. `outcome` is `fits`, `closest` or `none`, `best` is the number of the attempt to keep, and `note` is the result in words.
- `done`: the end, with every attempt, the note, the number of steps and the seconds.
- `error`: a dependency failed.

Closing the connection stops the search and cancels the run in progress.

## Streaming, progress and stop

`POST /api/ask/stream` runs the research loop and sends what happens while it happens, as one JSON object per line:

- `step`: a tool call was made, with its result;
- `sources`: the research is over, these are the sections that were read;
- `answer`: a piece of the answer, as the model writes it;
- `done`: the end, with the same content as the reply of `/api/ask`;
- `error`: a dependency failed. The HTTP status is already sent at that point, so the failure travels as the last event.

Closing the connection stops the run: the agent makes no further calls and the model stops writing. This is what the Stop button of the page does.

`GET /api/info` returns the version of the agent, which is the commit it was built from, and the name of the chat model. `GET /api/zoo` returns the choices a pipeline can be made of. The page shows both.

## The page

The page has three views, chosen by the part of the address after `#`.

- **Overview** (`#/`): what the project does, the pictures the pipelines are measured on, and the state of the cluster.
- **Fit** (`#/fit`): choose a device and two targets, and watch the search. A chart places every attempt by speed and accuracy, with the target as a lit corner. The pictures are marked right or wrong for the selected attempt.
- **Ask** (`#/ask`): ask a question on the documentation and see the steps of the search, the answer and the sections it read.

The views stay alive when hidden, so a search goes on while another view is on screen. The page is dark by default; the button at the top right switches to a light theme.

## The desktop app

The same page also runs as a Windows application, built with Tauri (`web/src-tauri/`). A Tauri app has two halves:

- the page, shown in a window by the browser engine that Windows already has (WebView2), so the application does not carry a browser of its own;
- a native program written in Rust, which can do what a page in a browser is not allowed to do.

The page calls functions of the native side by name. These functions are called commands. This app has one command, `gpu_status`: it runs `nvidia-smi` and returns the name of the graphics card, the video memory in use and the load. The page shows them at the top and refreshes them every two seconds, so the work of the model on the GPU is visible while it answers.

What the window may ask the native side is declared in `web/src-tauri/capabilities/default.json`. The content security policy in `web/src-tauri/tauri.conf.json` lets the page connect only to the agent at `http://127.0.0.1:8080`.

The desktop app does not contain the agent. It calls the same API as the page in the browser, at the address written in `web/.env.desktop`. The agent accepts these calls because it allows the origins that Tauri uses; the list is in the environment variable `CORS_ORIGINS`.

## Why MCP

The agent does not import the search code or the code that runs pipelines. It discovers the tools at runtime from the MCP servers, together with their instructions, so adding a capability means deploying a new tool on an MCP server. The same servers also work with any other MCP client.

## Configuration

The ConfigMap `llm-config` in the namespace `demo` holds `OLLAMA_URL`, `CHAT_MODEL` and `EMBED_MODEL`. The agent and docs-mcp read it as environment variables. The agent finds the MCP servers through `MCP_URL` and `SANDBOX_URL`. `NUM_CTX` sets the context size of the chat model: the default 6144 is the largest that keeps a 3B model entirely inside 4 GB of video memory. The sandbox server reads the image of a run from `BENCH_IMAGE` and the namespace of the runs from `SANDBOX_NAMESPACE`.

## The index

The index lives in the memory of the docs-mcp pod. It is built at the first search and rebuilt when the pod restarts. The markdown files are copied into the docs-mcp image at build time, so changing the documentation means building and deploying a new image.
