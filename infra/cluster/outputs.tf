output "public_ip" {
  value = aws_instance.k3s.public_ip
}

output "ssh_command" {
  value = "ssh -i ~/.ssh/devops-lab ubuntu@${aws_instance.k3s.public_ip}"
}

output "app_url" {
  value = "http://${aws_instance.k3s.public_ip}/"
}
