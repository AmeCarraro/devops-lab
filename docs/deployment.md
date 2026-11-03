# Pipeline and AWS

Status: the pipeline works end to end against the local cluster. A push to `main` is tested and built on GitHub, then deployed by the runner inside the cluster. `infra/state` and `infra/cluster` were applied on 2026-11-03 in `eu-north-1`: the node booted, `infra\cluster\deploy.ps1` deployed the agent and the monitoring stack, every Prometheus target was up, and a research run took about 5 minutes on the CPU of the node. `infra/budget` has never been applied.

## Pipeline

The pipeline is a GitHub Actions workflow, `.github/workflows/ci.yml`, with four jobs.

1. **test**: installs `requirements-dev.txt` and runs `pytest` on a runner hosted by GitHub. It runs on every push to `main` and on every pull request.
2. **test-web**: in `web/`, runs the linter, the build, which checks the types first, and the tests of the page. It runs together with **test**.
3. **build**: builds the images `agent`, `docs-mcp`, `sandbox-mcp` and `web`, and pushes them to the GitHub Container Registry, `ghcr.io`. The tag is the commit SHA. It also builds the `bench` image, but only when its version is new.
4. **deploy**: runs on our own runner, inside the cluster, selected with `runs-on: k3s`. It writes the registry secret and the ConfigMap `llm-config`, applies the manifests in `k8s/` and waits for the rollout of the four Deployments.

Build and deploy run only for a push to `main`. A pull request is only tested. The deploy job is skipped until the repository variable `OLLAMA_URL` is set, so the pipeline is green before a runner exists.

## The bench image in the pipeline

The bench image holds the models and the evaluation pictures. Building it downloads about 700 MB and takes several minutes, so it does not follow the commits. Its tag is the number in `bench/VERSION`. The build job asks the registry whether that tag exists and builds the image only when it does not. After a change to anything in `bench/`, raise the number in `bench/VERSION`: otherwise the old image stays in use.

The web image is built from the bench image as well: it copies the sample pictures out of it, so the page shows exactly the pictures the models see.

## How the cluster gets the bench image

A run in the sandbox starts long after the deploy, when the registry token of the deploy no longer works. So the bench image must already be on the node. The Deployment `sandbox-mcp` has an init container that uses the bench image and does nothing: starting it makes the node download the image during the rollout, while the token is still valid. On a cluster with several nodes this is not enough, because a run can land on another node.

## What must be applied by hand

`k8s/bootstrap/rbac.yaml` and `k8s/bootstrap/sandbox.yaml` are applied once by a cluster admin, not by the pipeline. The second one creates the namespace `sandbox` with its network policy and quota, the service account `sandbox-mcp` and the role that lets it start runs. The pipeline can deploy the sandbox server but cannot change these: what a run is allowed to do is not something a push can loosen.

```powershell
kubectl apply -f k8s\bootstrap\rbac.yaml -f k8s\bootstrap\sandbox.yaml
```

## Building the desktop app

A second workflow, `.github/workflows/desktop.yml`, builds the Windows application. It does not run at a push. It is started by hand: Actions, desktop, Run workflow. A Windows build takes several minutes, and on a private repository its minutes count double against the free quota.

1. **test**: on Linux, runs `cargo clippy` and `cargo test` on the native code.
2. **windows**: on a Windows runner hosted by GitHub, builds the page for the desktop, compiles the native side and makes the installer.

The result is an artifact named `ask-the-docs-windows`, at the bottom of the page of the run. It contains the plain executable and an installer. The executable is not signed, so Windows shows a warning the first time it is started.

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

Terraform runs in a container through `tf.ps1`, so nothing is installed on the PC. There are three stacks, each in its folder under `infra/`.

- `infra/state`: the S3 bucket that keeps the Terraform state of the cluster. It keeps every version of the state for 30 days, encrypts it, and refuses any request that is not HTTPS. It is applied once, and its own state stays in its folder, because a bucket cannot hold the state of the stack that creates it. It also writes `infra/cluster/backend.hcl`, the settings of the backend of the cluster. That file and the local state are git-ignored: they name the account.
- `infra/cluster`: one EC2 instance in the default VPC, `m7i-flex.large` with 2 vCPU and 8 GB. At first boot it installs k3s, Helm and Ollama, and pulls the two models. The security group accepts SSH and HTTP only from your IP address. The IAM role of the instance allows only Session Manager. The state is in S3 with a lock file next to it (`use_lockfile`), so two runs cannot change the cluster at the same time. CloudWatch alarms and a dashboard are in `monitoring.tf`.
- `infra/budget`: a monthly cost budget of 5 USD with email alerts at 40% and 80% of actual spend and at 100% of forecast spend. Apply it once and leave it. The alerts arrive hours late and do not stop the spending. An account that already has a budget made in the console does not need it.

`init`, `validate` and `plan` create nothing. `apply` creates resources that cost money.

## Sign in to AWS

Accounts of the new AWS experience sign in with a Google or Builder ID login and have no access keys. The AWS CLI borrows the session of the console instead, after a sign-in in the browser:

```powershell
docker run --rm -it -v C:\Users\<you>\.aws:/root/.aws amazon/aws-cli:latest login --remote --profile lab
```

The CLI runs in a container, which has no browser, so it prints a link. Open it, sign in, and paste the code that the page shows back into the terminal. The credentials last 12 hours and renew by themselves for 90 days. `tf.ps1` asks the CLI for them at every run and hands them to Terraform through environment variables, so they are never written to the repository or shown on a command line. The profile is `lab`, or the one named in `$env:AWS_LOGIN_PROFILE`.

Windows runs `.ps1` scripts only when its execution policy allows local scripts. `Get-ExecutionPolicy -List` shows it.

## Create, deploy, destroy

`infra/cluster/terraform.tfvars` (git-ignored) holds your public IP, for example `my_ip_cidr = "203.0.113.7/32"`. The node takes the public key `~/.ssh/devops-lab.pub`, made once with `ssh-keygen -t ed25519 -f ~/.ssh/devops-lab`.

```powershell
.\tf.ps1 state init
.\tf.ps1 state apply           # once: the bucket for the state
.\tf.ps1 cluster init          # reads backend.hcl
.\tf.ps1 cluster plan
.\tf.ps1 cluster apply
.\infra\cluster\deploy.ps1     # the app and the monitoring stack
.\tf.ps1 cluster destroy       # at the end of every session
```

`infra\cluster\deploy.ps1` waits for the first boot to finish, installs the monitoring stack with Helm, builds the images of the agent, the docs server and the page, copies them to the node over SSH, and applies the manifests with the same steps as the deploy job of the pipeline. The sandbox of the vision pipelines is not deployed on EC2: its bench image is large and the CPU of the node is busy with the LLM.

The page is at `http://<public_ip>/`, open only to your IP. Grafana is not exposed: see [Monitoring](monitoring.md) for the SSH tunnel.

## CloudWatch on the node

CloudWatch watches the node from outside, so it still reports when the node is too broken for Prometheus, which runs on it, to say anything. Prometheus and Grafana watch the app from inside.

| Alarm | When | Action |
|---|---|---|
| `devops-lab-node-system-check` | the system status check fails for 2 minutes: hardware or network under the node | recover: AWS moves the instance to healthy hardware, with the same ID, addresses and disk |
| `devops-lab-node-instance-check` | the instance status check fails for 3 minutes: the operating system does not answer | reboot |
| `devops-lab-node-cpu` | CPU above 90% for 15 minutes | none, it is a signal: on this node it means the LLM needs a GPU or a managed service |

The dashboard `devops-lab` shows the CPU, the network, the status checks and the three alarms. `.\tf.ps1 cluster output cloudwatch_dashboard` prints its address. With `alert_email` set in `terraform.tfvars`, the alarms also send an email, through an SNS topic. AWS first sends a confirmation message, and nothing arrives until it is confirmed. All of this is in the CloudWatch free tier.

## Cost on AWS

The instance costs about 0.10 USD per hour while it runs in Stockholm, the 30 GB disk and the public IPv4 address about 0.01 more. That is about 0.11 USD per hour, or 2.60 USD for a day left on. The S3 bucket of the state costs a fraction of a cent. Run `.\tf.ps1 cluster destroy` at the end of every session.

## The LLM on AWS

The node has no GPU: Ollama runs the chat model on its 2 vCPU. That works, and it is slow: a research run takes minutes instead of seconds, and the alert `AnswersSlow` is expected to fire. The dashboard shows where the time goes, mostly in reading the prompt. The options to go faster are an instance with a GPU or a managed model such as Amazon Bedrock.
