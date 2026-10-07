# Stores the GitHub token of the runner in the local cluster.
# The token is pasted into a password box, so it ends up neither on screen nor
# in the shell history. Run it again to replace the token.
$kubeconfig = Join-Path (Split-Path $PSScriptRoot -Parent) 'local\kubeconfig\kubeconfig.yaml'

while ($true) {
    $credential = Get-Credential -UserName 'github-token' -Message 'Paste the GitHub token of the runner into the password field'
    if (-not $credential) {
        Write-Host 'Cancelled, nothing changed.' -ForegroundColor Yellow
        exit 1
    }
    $plain = $credential.GetNetworkCredential().Password.Trim()
    # catches a wrong paste before the secret is written
    if ($plain -match '^(ghp_|github_pat_)[A-Za-z0-9_]+$') { break }
    Write-Host 'That does not look like a GitHub token: it should start with ghp_ or github_pat_. Try again.' -ForegroundColor Yellow
}

kubectl --kubeconfig $kubeconfig -n arc-runners create secret generic github-runner-token `
    --from-literal=github_token=$plain --dry-run=client -o yaml |
    kubectl --kubeconfig $kubeconfig apply -f -
