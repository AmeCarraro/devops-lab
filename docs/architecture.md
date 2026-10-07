# Architecture

devops-lab is a small agent platform: a documentation assistant that runs on Kubernetes and talks to a local LLM.

## Components

- **web** (`web/`): the page a person uses, written in TypeScript with React. It shows the steps of the agent while they happen, the answer while it is written, and the sections that were read. In Kubernetes it is the Deployment `web`: an nginx container that serves the built files.
- **agent** (`app/`): a FastAPI service, written in Python. `POST /api/ask` runs a research loop in which the LLM searches the documentation with tools, then writes the answer with its sources. In Kubernetes it is the Deployment `demo-api`, with 2 replicas.
- **docs-mcp** (`mcp-server/`): an MCP server with two tools, `search_docs` and `search_by_name`. It splits the markdown files of `docs/` into chunks, one per section. In Kubernetes it is the Deployment `docs-mcp`, listening on port 8001 at the path `/mcp`.
- **Ollama**: serves the chat model and the embedding model. Locally it runs on the Windows host, outside the cluster, so that it can use the GPU.
- **Traefik**: the ingress controller that ships with k3s. It routes `/api` to the agent, `/mcp` to docs-mcp and every other path to the web page, so the three services share one address.

## Why two languages

The page is TypeScript because a browser only runs JavaScript, and TypeScript is JavaScript with types. The agent is Python because that is where the libraries for models and data are. The two meet in the API: `web/src/api.ts` describes the events of the agent as types, so the compiler checks that the page handles every kind of event.

## The tools

- `search_docs` searches by meaning. It embeds the query with Ollama (`/api/embed`) and returns the chunks closest to it.
- `search_by_name` opens sections by the name of their page or heading. It needs no embeddings. When nothing has that name, it answers with the list of the names that exist.
- `finish` leaves the research loop. It is the only tool that belongs to the agent and not to the MCP server, because it is control flow and not a capability. Its argument `missing` says what the question asks that no excerpt answers yet.

## Request flow

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

## Streaming, progress and stop

`POST /api/ask/stream` runs the same loop and sends what happens while it happens, as one JSON object per line:

- `step`: a tool call was made, with its result;
- `sources`: the research is over, these are the sections that were read;
- `answer`: a piece of the answer, as the model writes it;
- `done`: the end, with the same content as the reply of `/api/ask`;
- `error`: a dependency failed. The HTTP status is already sent at that point, so the failure travels as the last event.

Closing the connection stops the run: the agent makes no further calls and the model stops writing. This is what the Stop button of the page does.

`GET /api/info` returns the version of the agent, which is the commit it was built from, and the name of the chat model. The page shows both at the top.

## Why MCP

The agent does not import the search code. It discovers the tools at runtime from the MCP server, together with the instructions of the server on how to use them, so adding a capability means deploying a new tool on an MCP server, without touching the agent. The same server also works with other MCP clients, for example Claude Code.

## Configuration

The ConfigMap `llm-config` in the namespace `demo` holds `OLLAMA_URL`, `CHAT_MODEL` and `EMBED_MODEL`. Both services read it as environment variables. The agent finds the MCP server through `MCP_URL`. `NUM_CTX` sets the context size of the chat model: the default 6144 is the largest that keeps a 3B model entirely inside 4 GB of video memory.

## The index

The index lives in the memory of the docs-mcp pod. It is built at the first search and rebuilt when the pod restarts. The markdown files are copied into the docs-mcp image at build time, so changing the documentation means building and deploying a new image.
