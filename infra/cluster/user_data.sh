#!/bin/bash
# Runs once as root at first boot. Log: /var/log/cloud-init-output.log
set -euxo pipefail

# k3s: single-node Kubernetes (API server, kubelet, containerd, Traefik ingress)
# same version as the local cluster in local/compose.yaml
curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION="v1.34.1+k3s1" sh -

until [ -f /etc/rancher/k3s/k3s.yaml ]; do sleep 2; done

# kubeconfig for the ubuntu user, so kubectl/helm work without sudo
mkdir -p /home/ubuntu/.kube
cp /etc/rancher/k3s/k3s.yaml /home/ubuntu/.kube/config
chown -R ubuntu:ubuntu /home/ubuntu/.kube
chmod 600 /home/ubuntu/.kube/config
echo 'export KUBECONFIG=$HOME/.kube/config' >> /home/ubuntu/.bashrc

# Helm, used to install the GitHub Actions runner charts
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
