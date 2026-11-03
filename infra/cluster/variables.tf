variable "region" {
  description = "AWS region. Accounts of the new AWS experience have a fixed one: Stockholm for Italy"
  type        = string
  default     = "eu-north-1"
}

variable "instance_type" {
  description = "EC2 instance type for the single k3s node"
  type        = string
  # 2 vCPU and 8 GB: k3s, the monitoring stack and a 3B model on the CPU fit together
  default = "m7i-flex.large"
}

variable "my_ip_cidr" {
  description = "Your public IP in CIDR form, e.g. 203.0.113.7/32 (only this IP can reach SSH and HTTP)"
  type        = string
}

variable "ssh_public_key_path" {
  description = "Path to the SSH public key to install on the instance"
  type        = string
  default     = "~/.ssh/devops-lab.pub"
}

variable "chat_model" {
  description = "Ollama model that runs the agent, pulled at first boot"
  type        = string
  default     = "granite4.1:3b"
}

variable "embed_model" {
  description = "Ollama model that turns the documentation into vectors for the search"
  type        = string
  default     = "nomic-embed-text"
}

variable "alert_email" {
  description = "Email for the CloudWatch alarms. Empty: the alarms show only in the console"
  type        = string
  default     = ""
}
