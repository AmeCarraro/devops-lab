# Terraform inside a container: nothing to install on the PC.
# Usage: .\tf.ps1 state apply      .\tf.ps1 cluster plan      .\tf.ps1 cluster destroy
# fmt/validate are free and offline; init, plan and apply need you signed in to AWS
# (aws login, see docs/deployment.md); apply creates billable resources.
param(
    [Parameter(Mandatory)][ValidateSet('state', 'cluster', 'budget')][string]$Stack,
    [Parameter(ValueFromRemainingArguments)][string[]]$TfArgs
)
# the profile of `aws login` whose short-lived credentials are handed to Terraform
$awsProfile = if ($env:AWS_LOGIN_PROFILE) { $env:AWS_LOGIN_PROFILE } else { 'lab' }

$mounts = @(
    # all of infra/, so the state stack can write the backend settings of the cluster
    '-v', "$PSScriptRoot\infra:/infra",
    # providers live in a Docker volume: faster than the Windows filesystem
    '-v', 'devops-lab-tf:/tfdata',
    '-e', "TF_DATA_DIR=/tfdata/$Stack"
)
# only the public key is shared with the container, never the private one
if (Test-Path "$HOME\.ssh\devops-lab.pub") { $mounts += '-v', "$HOME\.ssh\devops-lab.pub:/root/.ssh/devops-lab.pub:ro" }

# Credentials: the AWS CLI exports the temporary keys of the `aws login` session (it renews
# them when they expire). They go to Terraform through environment variables of this
# process, so they are never written to disk or shown on a command line
if (Test-Path "$HOME\.aws") {
    $exported = docker run --rm -v "$HOME\.aws:/root/.aws" amazon/aws-cli:latest `
        configure export-credentials --profile $awsProfile --format env-no-export 2>$null
    foreach ($line in $exported) {
        if ($line -match '^(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|AWS_SESSION_TOKEN)=(.+)$') {
            Set-Item "env:$($Matches[1])" $Matches[2]
            $mounts += '-e', $Matches[1]
        }
    }
}

# the cluster keeps its state in S3: init reads the bucket from backend.hcl, written by the state stack
if ($Stack -eq 'cluster' -and $TfArgs -and $TfArgs[0] -eq 'init' -and (Test-Path "$PSScriptRoot\infra\cluster\backend.hcl")) {
    $TfArgs += '-backend-config=backend.hcl'
}

$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
docker run --rm $tty @mounts -w "/infra/$Stack" hashicorp/terraform:1.16.7 @TfArgs
