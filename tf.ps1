# Terraform inside a container: nothing to install on the PC.
# Usage: .\tf.ps1 cluster plan      .\tf.ps1 budget apply
# init/validate/fmt are free and offline; plan needs AWS credentials; apply creates billable resources.
param(
    [Parameter(Mandatory)][ValidateSet('cluster', 'budget')][string]$Stack,
    [Parameter(ValueFromRemainingArguments)][string[]]$TfArgs
)

$mounts = @(
    '-v', "$PSScriptRoot\infra\${Stack}:/work",
    # providers live in a Docker volume: faster than the Windows filesystem
    '-v', 'devops-lab-tf:/tfdata',
    '-e', "TF_DATA_DIR=/tfdata/$Stack"
)
if (Test-Path "$HOME\.aws") { $mounts += '-v', "$HOME\.aws:/root/.aws:ro" }
# only the public key is shared with the container, never the private one
if (Test-Path "$HOME\.ssh\devops-lab.pub") { $mounts += '-v', "$HOME\.ssh\devops-lab.pub:/root/.ssh/devops-lab.pub:ro" }

$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
docker run --rm $tty @mounts -w /work hashicorp/terraform:1.9.8 @TfArgs
