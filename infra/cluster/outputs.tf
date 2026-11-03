output "public_ip" {
  value = aws_instance.k3s.public_ip
}

output "private_ip" {
  description = "Where the pods reach Ollama, which runs on the node itself"
  value       = aws_instance.k3s.private_ip
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/devops-lab ubuntu@${aws_instance.k3s.public_ip}"
}

output "app_url" {
  value = "http://${aws_instance.k3s.public_ip}/"
}

output "grafana_tunnel" {
  description = "Grafana is not exposed: open this tunnel, then http://grafana.localhost:8081/d/devops-lab-agent"
  value       = "ssh -i ~/.ssh/devops-lab -N -L 8081:127.0.0.1:80 ubuntu@${aws_instance.k3s.public_ip}"
}

output "cloudwatch_dashboard" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}#dashboards/dashboard/${aws_cloudwatch_dashboard.node.dashboard_name}"
}
