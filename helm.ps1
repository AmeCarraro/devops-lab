# Helm inside a container, talking to the local k3s cluster: nothing to install on the PC.
# Usage: .\helm.ps1 list -A
# The container shares the network of the k3s node, so the address in the
# kubeconfig (127.0.0.1:6443) is the API server.
$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
docker run --rm $tty --network container:devops-lab-k3s `
    -v "$PSScriptRoot\local\kubeconfig:/kube:ro" -e KUBECONFIG=/kube/kubeconfig.yaml `
    -v "${PSScriptRoot}:/work:ro" -w /work `
    alpine/helm:4.3.0 @args
