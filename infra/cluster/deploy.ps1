# Deploy the agent and the monitoring stack to the EC2 node made by Terraform (infra/cluster).
# Like local\deploy.ps1 there is no registry: the images are built on this PC and copied
# to the node over SSH, then the manifests are applied on the node.
# Needs Docker Desktop, the node up (.\tf.ps1 cluster apply) and the key ~/.ssh/devops-lab.
# The sandbox for the vision pipelines is not deployed here: its bench image is large and
# the CPU of the node is busy with the LLM.
# Usage: .\infra\cluster\deploy.ps1            .\infra\cluster\deploy.ps1 -ChatModel qwen3:4b
param(
    [string]$ChatModel = 'granite4.1:3b',
    [string]$EmbedModel = 'nomic-embed-text'
)

$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$tag = Get-Date -Format 'yyyyMMdd-HHmmss'
$agentImage = "devops-lab-agent:$tag"
$mcpImage = "devops-lab-docs-mcp:$tag"
$webImage = "devops-lab-web:$tag"
$benchImage = 'devops-lab-bench:' + (Get-Content (Join-Path $root 'bench\VERSION')).Trim()
$monitoringChart = (Get-Content (Join-Path $root 'k8s\monitoring\VERSION')).Trim()

# a new node gets a new host key: accept it the first time, in a file kept apart for the lab
$ssh = @('-i', "$HOME\.ssh\devops-lab", '-o', 'StrictHostKeyChecking=accept-new',
    '-o', "UserKnownHostsFile=$HOME\.ssh\devops-lab_known_hosts", '-o', 'ConnectTimeout=10')

function Stop-Deploy($message) { Write-Host "FAILED: $message" -ForegroundColor Red; exit 1 }
function Assert-Ok($step) { if ($LASTEXITCODE -ne 0) { Stop-Deploy $step } }
# A bash script for the node, sent on standard input. PowerShell adds Windows line ends and a
# byte order mark, which bash would read as part of the first command: tr and sed remove them.
# A non-interactive SSH session skips .bashrc, so the kubeconfig of the ubuntu user is named here
function Invoke-Node($script) {
    $script | ssh @ssh "ubuntu@$ip" "tr -d '\r' | sed '1s/^\xEF\xBB\xBF//' | KUBECONFIG=/home/ubuntu/.kube/config bash -s"
}

Write-Host "== 1/5 node" -ForegroundColor Cyan
$outputs = (& (Join-Path $root 'tf.ps1') cluster output -json) | Out-String | ConvertFrom-Json
if (-not $outputs.public_ip) { Stop-Deploy 'no node in the Terraform state: run .\tf.ps1 cluster apply first' }
$ip = $outputs.public_ip.value
$privateIp = $outputs.private_ip.value
foreach ($i in 1..30) {
    ssh @ssh "ubuntu@$ip" true 2>$null
    if ($LASTEXITCODE -eq 0) { break }
    Start-Sleep -Seconds 10
}
Assert-Ok "SSH to $ip"
# the first boot installs k3s, Helm and Ollama and pulls the models: wait until it is over
ssh @ssh "ubuntu@$ip" 'sudo cloud-init status --wait > /dev/null; sudo cloud-init status'
Assert-Ok 'first boot of the node'

Write-Host "== 2/5 monitoring stack $monitoringChart" -ForegroundColor Cyan
# the manifests travel to the node once; every later step reads them there
ssh @ssh "ubuntu@$ip" 'rm -rf /tmp/devops-lab && mkdir -p /tmp/devops-lab'
scp @ssh -q -r (Join-Path $root 'k8s') "ubuntu@${ip}:/tmp/devops-lab/"
Assert-Ok 'copy manifests'
Invoke-Node @"
set -euo pipefail
kubectl create namespace monitoring --dry-run=client -o yaml | kubectl apply -f -
# the Grafana admin password is made on the node the first time and lives only in the cluster
kubectl -n monitoring get secret grafana-admin > /dev/null 2>&1 ||
  kubectl -n monitoring create secret generic grafana-admin --from-literal=admin-user=admin \
    --from-literal=admin-password="`$(openssl rand -base64 18)"
helm upgrade --install monitoring oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
  --version $monitoringChart --namespace monitoring -f /tmp/devops-lab/k8s/monitoring/values.yaml --wait --timeout 10m
"@
Assert-Ok 'helm monitoring'

Write-Host "== 3/5 build $tag" -ForegroundColor Cyan
docker build -q --build-arg APP_VERSION=$tag -t $agentImage $root
Assert-Ok 'build agent'
docker build -q -f (Join-Path $root 'mcp-server\Dockerfile') -t $mcpImage $root
Assert-Ok 'build docs-mcp'
docker image inspect $benchImage 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) { Stop-Deploy "the web page takes its pictures from ${benchImage}: run local\deploy.ps1 once first" }
docker build -q -f (Join-Path $root 'web\Dockerfile') --build-arg BENCH_IMAGE=$benchImage -t $webImage $root
Assert-Ok 'build web'

Write-Host "== 4/5 copy images to the node" -ForegroundColor Cyan
# one archive for the three images: the layers they share travel once
$tar = Join-Path $env:TEMP 'devops-lab-images.tar'
docker save -o $tar $agentImage $mcpImage $webImage
Assert-Ok 'docker save'
Write-Host ("   {0:N0} MB to upload" -f ((Get-Item $tar).Length / 1MB))
scp @ssh -q $tar "ubuntu@${ip}:/tmp/images.tar"
Assert-Ok 'upload images'
Remove-Item $tar
ssh @ssh "ubuntu@$ip" 'sudo k3s ctr -n k8s.io images import /tmp/images.tar > /dev/null && rm /tmp/images.tar'
Assert-Ok 'image import'

Write-Host "== 5/5 apply manifests" -ForegroundColor Cyan
# The same steps as the deploy job of the pipeline. Ollama runs on the node itself,
# so the pods reach it at the private address of the node
Invoke-Node @"
set -euo pipefail
cd /tmp/devops-lab
kubectl apply -f k8s/bootstrap/rbac.yaml
kubectl -n demo create configmap llm-config \
  --from-literal=OLLAMA_URL=http://${privateIp}:11434 \
  --from-literal=CHAT_MODEL=$ChatModel \
  --from-literal=EMBED_MODEL=$EmbedModel \
  --dry-run=client -o yaml | kubectl apply -f -
sed 's|IMAGE_PLACEHOLDER|$agentImage|' k8s/deployment.yaml | kubectl apply -f -
sed 's|MCP_IMAGE_PLACEHOLDER|$mcpImage|' k8s/docs-mcp.yaml | kubectl apply -f -
sed 's|WEB_IMAGE_PLACEHOLDER|$webImage|' k8s/web.yaml | kubectl apply -f -
kubectl apply -f k8s/service.yaml -f k8s/ingress.yaml
kubectl apply -f k8s/monitoring/servicemonitor.yaml -f k8s/monitoring/alerts.yaml
kubectl -n demo create configmap dashboard-agent --from-file=k8s/monitoring/dashboards/agent.json \
  --dry-run=client -o yaml | kubectl label --local -f - grafana_dashboard=1 -o yaml | kubectl apply -f -
kubectl -n demo rollout status deployment/docs-mcp --timeout=300s
kubectl -n demo rollout status deployment/demo-api --timeout=300s
kubectl -n demo rollout status deployment/web --timeout=300s
"@
Assert-Ok 'apply manifests'

$info = Invoke-RestMethod "http://$ip/api/info" -TimeoutSec 20
Write-Host "`nVersion $($info.version) answers on $ip" -ForegroundColor Green
Write-Host "Page:    http://$ip/" -ForegroundColor Green
Write-Host "Grafana: open the tunnel, then http://grafana.localhost:8081/d/devops-lab-agent" -ForegroundColor Green
Write-Host "         ssh -i ~/.ssh/devops-lab -N -L 8081:127.0.0.1:80 ubuntu@$ip" -ForegroundColor Green
Write-Host "Remember: .\tf.ps1 cluster destroy at the end of the session" -ForegroundColor Yellow
