#!/bin/bash
# Runs once as root at first boot. Log: /var/log/cloud-init-output.log
# A Terraform template: $${name} is filled in by Terraform, plain $NAME is left to bash
set -euxo pipefail
# cloud-init runs this without HOME, and the ollama CLI refuses to start without it
export HOME=/root

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

# Helm, which installs the monitoring stack (and the GitHub Actions runner charts)
curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash

# Ollama: the LLM runs on this node, on the CPU. It listens on every address so that the
# pods reach it at the IP of the node; the security group keeps port 11434 closed outside
curl -fsSL https://ollama.com/install.sh | sh
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/listen.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
systemctl daemon-reload
systemctl restart ollama
until curl -sf http://127.0.0.1:11434/api/tags > /dev/null; do sleep 2; done
ollama pull ${chat_model}
ollama pull ${embed_model}
