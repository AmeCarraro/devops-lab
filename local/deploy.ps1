# Local equivalent of the pipeline: build the images, load them into the local
# k3s node and apply the manifests. Needs Docker Desktop and Ollama, costs nothing.
# Usage: .\local\deploy.ps1            .\local\deploy.ps1 -ChatModel qwen3:4b
param(
    [string]$ChatModel = 'granite4.1:3b',
    [string]$EmbedModel = 'nomic-embed-text'
)

$root = Split-Path $PSScriptRoot -Parent
$env:KUBECONFIG = Join-Path $PSScriptRoot 'kubeconfig\kubeconfig.yaml'
$node = 'devops-lab-k3s'

# a new tag on every run, like the commit SHA in CI, so Kubernetes rolls out the new version
$tag = Get-Date -Format 'yyyyMMdd-HHmmss'
$agentImage = "devops-lab-agent:$tag"
$mcpImage = "devops-lab-docs-mcp:$tag"
$webImage = "devops-lab-web:$tag"
$sandboxImage = "devops-lab-sandbox-mcp:$tag"
# the bench image changes rarely and is large: its tag is the number in bench\VERSION,
# and it is built and loaded only when that number is new
$benchImage = 'devops-lab-bench:' + (Get-Content (Join-Path $root 'bench\VERSION')).Trim()
# Prometheus, Alertmanager and Grafana come from one Helm chart, at the version in this file
$monitoringChart = (Get-Content (Join-Path $root 'k8s\monitoring\VERSION')).Trim()

function Stop-Deploy($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }
function Assert-Ok($step) { if ($LASTEXITCODE -ne 0) { Stop-Deploy $step } }

Write-Host "== 1/6 Ollama on the host" -ForegroundColor Cyan
try { $models = (Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models.name }
catch { Stop-Deploy 'Ollama is not running on this PC: start it and retry' }
foreach ($model in $ChatModel, $EmbedModel) {
    if ($models -notcontains $model -and $models -notcontains "${model}:latest") {
        Stop-Deploy "model $model is missing: run 'ollama pull $model'"
    }
}

Write-Host "== 2/6 cluster" -ForegroundColor Cyan
docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d
Assert-Ok 'docker compose up'
foreach ($i in 1..60) {
    $ready = kubectl get nodes --no-headers 2>$null | Select-String ' Ready '
    if ($ready) { break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Stop-Deploy 'k3s node not Ready' }

Write-Host "== 3/6 monitoring stack $monitoringChart" -ForegroundColor Cyan
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
Assert-Ok 'namespace monitoring'
# The Grafana admin password is made on the first run and lives only in the cluster
kubectl -n monitoring get secret grafana-admin 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    $bytes = New-Object byte[] 18
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $password = [Convert]::ToBase64String($bytes)
    kubectl -n monitoring create secret generic grafana-admin --from-literal=admin-user=admin "--from-literal=admin-password=$password"
    Assert-Ok 'grafana password'
}
# Helm in a container on the network of the node, like helm.ps1. Installed the first time,
# upgraded in place afterwards; --wait returns when Prometheus and Grafana are ready
docker run --rm --network "container:$node" `
    -v "${PSScriptRoot}\kubeconfig:/kube:ro" -e KUBECONFIG=/kube/kubeconfig.yaml `
    -v "$(Join-Path $root 'k8s\monitoring'):/values:ro" `
    alpine/helm:4.3.0 upgrade --install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack `
    --version $monitoringChart --namespace monitoring -f /values/values.yaml --wait --timeout 10m
Assert-Ok 'helm monitoring'

Write-Host "== 4/6 build $tag" -ForegroundColor Cyan
docker build -q --build-arg APP_VERSION=$tag -t $agentImage $root
Assert-Ok 'build agent'
docker build -q -f (Join-Path $root 'mcp-server\Dockerfile') -t $mcpImage $root
Assert-Ok 'build docs-mcp'
docker build -q -f (Join-Path $root 'sandbox\Dockerfile') -t $sandboxImage $root
Assert-Ok 'build sandbox-mcp'
docker image inspect $benchImage 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "   $benchImage is new: it downloads models and pictures, about ten minutes" -ForegroundColor Yellow
    docker build -q -f (Join-Path $root 'bench\Dockerfile') -t $benchImage $root
    Assert-Ok 'build bench'
}
# the page takes the sample pictures from the bench image
docker build -q -f (Join-Path $root 'web\Dockerfile') --build-arg BENCH_IMAGE=$benchImage -t $webImage $root
Assert-Ok 'build web'

# No registry locally: copy the images straight into the node's containerd
Write-Host "== 5/6 load images into the node" -ForegroundColor Cyan
$tar = Join-Path $env:TEMP 'devops-lab-images.tar'
$images = @($agentImage, $mcpImage, $webImage, $sandboxImage)
$onNode = docker exec $node ctr -n k8s.io images ls -q
if (-not ($onNode | Select-String -SimpleMatch "/$benchImage")) { $images += $benchImage }
docker save -o $tar @images
Assert-Ok 'docker save'
docker cp $tar "${node}:/tmp/images.tar"
docker exec $node ctr -n k8s.io images import /tmp/images.tar
Assert-Ok 'image import'
docker exec $node rm /tmp/images.tar
Remove-Item $tar

Write-Host "== 6/6 apply manifests" -ForegroundColor Cyan
kubectl apply -f (Join-Path $root 'k8s\bootstrap\rbac.yaml') -f (Join-Path $root 'k8s\bootstrap\sandbox.yaml')
Assert-Ok 'apply rbac and sandbox'

# Pods cannot resolve host.docker.internal (their DNS is CoreDNS, not Docker's),
# so resolve it on the node and give them the IP of the host, where Ollama runs
$lookup = docker exec $node nslookup host.docker.internal 2>$null
$hostIp = ($lookup | Select-String 'Address:\s+(\d+\.\d+\.\d+\.\d+)\s*$' | Select-Object -First 1).Matches.Groups[1].Value
if (-not $hostIp) { Stop-Deploy 'cannot find the address of the Docker host' }
kubectl -n demo create configmap llm-config `
    --from-literal=OLLAMA_URL="http://${hostIp}:11434" `
    --from-literal=CHAT_MODEL=$ChatModel `
    --from-literal=EMBED_MODEL=$EmbedModel `
    --dry-run=client -o yaml | kubectl apply -f -
Assert-Ok 'apply configmap'

(Get-Content (Join-Path $root 'k8s\deployment.yaml') -Raw).Replace('IMAGE_PLACEHOLDER', $agentImage) | kubectl apply -f -
Assert-Ok 'apply agent'
(Get-Content (Join-Path $root 'k8s\docs-mcp.yaml') -Raw).Replace('MCP_IMAGE_PLACEHOLDER', $mcpImage) | kubectl apply -f -
Assert-Ok 'apply docs-mcp'
(Get-Content (Join-Path $root 'k8s\web.yaml') -Raw).Replace('WEB_IMAGE_PLACEHOLDER', $webImage) | kubectl apply -f -
Assert-Ok 'apply web'
$sandbox = (Get-Content (Join-Path $root 'k8s\sandbox-mcp.yaml') -Raw).Replace('SANDBOX_IMAGE_PLACEHOLDER', $sandboxImage)
$sandbox.Replace('BENCH_IMAGE_PLACEHOLDER', $benchImage) | kubectl apply -f -
Assert-Ok 'apply sandbox-mcp'
kubectl apply -f (Join-Path $root 'k8s\service.yaml') -f (Join-Path $root 'k8s\ingress.yaml')
Assert-Ok 'apply service/ingress'
# What Prometheus scrapes and alerts on, and the Grafana dashboard, travel with the app
kubectl apply -f (Join-Path $root 'k8s\monitoring\servicemonitor.yaml') -f (Join-Path $root 'k8s\monitoring\alerts.yaml')
Assert-Ok 'apply servicemonitor/alerts'
$dashboard = Join-Path $root 'k8s\monitoring\dashboards\agent.json'
kubectl -n demo create configmap dashboard-agent "--from-file=$dashboard" --dry-run=client -o yaml |
    kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -
Assert-Ok 'apply dashboard'
kubectl -n demo rollout status deployment/docs-mcp --timeout=180s
Assert-Ok 'rollout docs-mcp'
kubectl -n demo rollout status deployment/sandbox-mcp --timeout=180s
Assert-Ok 'rollout sandbox-mcp'
kubectl -n demo rollout status deployment/demo-api --timeout=180s
Assert-Ok 'rollout agent'
kubectl -n demo rollout status deployment/web --timeout=180s
Assert-Ok 'rollout web'

Write-Host "`nPage: http://127.0.0.1:8080/" -ForegroundColor Green
Write-Host "API:  http://127.0.0.1:8080/api/docs" -ForegroundColor Green
Write-Host "MCP:  http://127.0.0.1:8080/mcp" -ForegroundColor Green
Write-Host "Grafana:      http://grafana.localhost:8080/d/devops-lab-agent" -ForegroundColor Green
Write-Host "Prometheus:   http://prometheus.localhost:8080/alerts" -ForegroundColor Green
Write-Host "Alertmanager: http://alertmanager.localhost:8080" -ForegroundColor Green
