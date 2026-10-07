# Pipeline and AWS

Status: the pipeline works end to end against the local cluster. A push to `main` is tested and built on GitHub, then deployed by the runner inside the cluster. Nothing has been created on AWS yet: `terraform validate` passes, but the AWS part has never been applied.

## Pipeline

The pipeline is a GitHub Actions workflow, `.github/workflows/ci.yml`, with three jobs.

1. **test**: installs `requirements-dev.txt` and runs `pytest` on a runner hosted by GitHub. It runs on every push to `main` and on every pull request.
2. **build**: builds the two images, `agent` and `docs-mcp`, and pushes them to the GitHub Container Registry, `ghcr.io`. The tag is the commit SHA.
3. **deploy**: runs on our own runner, inside the cluster, selected with `runs-on: k3s`. It writes the registry secret and the ConfigMap `llm-config`, applies the manifests in `k8s/` and waits for the rollout of both Deployments.

Build and deploy run only for a push to `main`. A pull request is only tested. The deploy job is skipped until the repository variable `OLLAMA_URL` is set, so the pipeline is green before a runner exists.

## What the pipeline needs in GitHub

- A repository variable `OLLAMA_URL` with the address of Ollama as seen from the pods. It is set in Settings, Secrets and variables, Actions, Variables. Setting it is what turns the deploy job on. `CHAT_MODEL` and `EMBED_MODEL` are optional variables with a default.
- No secret. The jobs use `GITHUB_TOKEN`, the token that GitHub creates for every run, to push the images and to let the cluster pull them.

## How the cluster pulls the images

Images on `ghcr.io` are private by default. The deploy job stores the token of the run in the secret `ghcr`, and the cluster uses it to pull the images during the rollout. The token stops working when the job ends, so no long-lived registry password stays in the cluster. The images stay in the cache of the node. A new node has an empty cache: run the pipeline again to deploy on it.

## The runner

The runner is installed with Actions Runner Controller (ARC), the official way to run GitHub Actions runners on Kubernetes. It is made of two Helm charts:

- the controller, in the namespace `arc-systems`;
- a runner scale set named `k3s`, in the namespace `arc-runners`, with the values in `runner/values.yaml`. The name of the Helm release is the label that a job selects with `runs-on`.

No runner pod exists while nothing runs. A small listener pod waits for jobs. When a job arrives, the controller creates a runner pod, the pod runs the job and is deleted.

The steps of a job run as the service account `deployer`. Its permissions are in `k8s/bootstrap/rbac.yaml`: it can manage Deployments, Services, Ingresses, Secrets and ConfigMaps in the namespace `demo` and nothing else. The deploy job needs no kubeconfig and the Kubernetes API is not exposed to the internet.

## Install the runner

The scale set registers on GitHub with a personal access token (classic, scope `repo`). The token is stored in the Kubernetes secret `github-runner-token` and is never committed. `runner\set-token.ps1` opens a password box for the token and writes the secret; run it again to replace the token.

```powershell
kubectl apply -f k8s\bootstrap\rbac.yaml
.\runner\set-token.ps1
.\helm.ps1 install arc --namespace arc-systems --create-namespace oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set-controller --version 0.15.0
.\helm.ps1 install k3s --namespace arc-runners -f runner/values.yaml --set githubConfigUrl=https://github.com/<user>/<repository> oci://ghcr.io/actions/actions-runner-controller-charts/gha-runner-scale-set --version 0.15.0
```

`helm.ps1` runs Helm in a container against the local cluster, so Helm is not installed on the PC.

## Public or private repository

Keep the repository private while it has a self-hosted runner. On a public repository anyone can open a pull request, and a pull request can change the workflow so that its code runs on our runner, inside the cluster. GitHub advises against self-hosted runners on public repositories.

## Cost of GitHub

Nothing. A private repository on the free plan includes 2,000 minutes per month on the runners hosted by GitHub, and usage stops when they are used up unless a payment method is on file. Jobs on a self-hosted runner are free. The Container Registry is currently free.

## AWS

Terraform runs in a container through `tf.ps1`, so nothing is installed on the PC.

- `infra/budget`: a monthly cost budget of 5 USD with email alerts at 40% and 80% of actual spend and at 100% of forecast spend. Apply it once and leave it. The alerts arrive hours late and do not stop the spending.
- `infra/cluster`: one EC2 instance `t3.small` with k3s installed at first boot, and a security group that accepts SSH and HTTP only from your IP address.

```powershell
.\tf.ps1 budget apply
.\tf.ps1 cluster plan
.\tf.ps1 cluster apply
.\tf.ps1 cluster destroy
```

`init`, `validate` and `plan` create nothing. `apply` creates resources that cost money.

## Cost on AWS

The instance costs about 0.03 USD per hour while it runs, disk and public IP included. Left on all day it costs about 0.70 USD per day. Run `.\tf.ps1 cluster destroy` at the end of every session.

## The LLM on AWS

There is no GPU on the `t3.small` instance and no Ollama in the cluster yet. Where the model runs on AWS is still to be decided.
