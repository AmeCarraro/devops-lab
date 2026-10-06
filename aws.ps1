# AWS CLI inside a container: nothing to install on the PC.
# Usage: .\aws.ps1 configure      .\aws.ps1 sts get-caller-identity
$tty = if ([Console]::IsInputRedirected) { '-i' } else { '-it' }
docker run --rm $tty -v "$HOME\.aws:/root/.aws" amazon/aws-cli:latest @args
