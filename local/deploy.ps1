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

function Stop-Deploy($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }
function Assert-Ok($step) { if ($LASTEXITCODE -ne 0) { Stop-Deploy $step } }

Write-Host "== 1/5 Ollama on the host" -ForegroundColor Cyan
try { $models = (Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models.name }
catch { Stop-Deploy 'Ollama is not running on this PC: start it and retry' }
foreach ($model in $ChatModel, $EmbedModel) {
    if ($models -notcontains $model -and $models -notcontains "${model}:latest") {
        Stop-Deploy "model $model is missing: run 'ollama pull $model'"
    }
}

Write-Host "== 2/5 cluster" -ForegroundColor Cyan
docker compose -f (Join-Path $PSScriptRoot 'compose.yaml') up -d
Assert-Ok 'docker compose up'
foreach ($i in 1..60) {
    $ready = kubectl get nodes --no-headers 2>$null | Select-String ' Ready '
    if ($ready) { break }
    Start-Sleep -Seconds 2
}
if (-not $ready) { Stop-Deploy 'k3s node not Ready' }

Write-Host "== 3/5 build $tag" -ForegroundColor Cyan
docker build -q --build-arg APP_VERSION=$tag -t $agentImage $root
Assert-Ok 'build agent'
docker build -q -f (Join-Path $root 'mcp-server\Dockerfile') -t $mcpImage $root
Assert-Ok 'build docs-mcp'
docker build -q -f (Join-Path $root 'web\Dockerfile') -t $webImage $root
Assert-Ok 'build web'

# No registry locally: copy the images straight into the node's containerd
Write-Host "== 4/5 load images into the node" -ForegroundColor Cyan
$tar = Join-Path $env:TEMP 'devops-lab-images.tar'
docker save -o $tar $agentImage $mcpImage $webImage
Assert-Ok 'docker save'
docker cp $tar "${node}:/tmp/images.tar"
docker exec $node ctr -n k8s.io images import /tmp/images.tar
Assert-Ok 'image import'
docker exec $node rm /tmp/images.tar
Remove-Item $tar

Write-Host "== 5/5 apply manifests" -ForegroundColor Cyan
kubectl apply -f (Join-Path $root 'k8s\bootstrap\rbac.yaml')
Assert-Ok 'apply rbac'

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
kubectl apply -f (Join-Path $root 'k8s\service.yaml') -f (Join-Path $root 'k8s\ingress.yaml')
Assert-Ok 'apply service/ingress'
kubectl -n demo rollout status deployment/docs-mcp --timeout=180s
Assert-Ok 'rollout docs-mcp'
kubectl -n demo rollout status deployment/demo-api --timeout=180s
Assert-Ok 'rollout agent'
kubectl -n demo rollout status deployment/web --timeout=180s
Assert-Ok 'rollout web'

Write-Host "`nPage: http://127.0.0.1:8080/" -ForegroundColor Green
Write-Host "API:  http://127.0.0.1:8080/api/docs" -ForegroundColor Green
Write-Host "MCP:  http://127.0.0.1:8080/mcp" -ForegroundColor Green
