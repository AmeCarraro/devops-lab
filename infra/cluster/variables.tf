variable "region" {
  description = "AWS region"
  type        = string
  default     = "eu-west-1"
}

variable "instance_type" {
  description = "EC2 instance type for the single k3s node"
  type        = string
  default     = "t3.small"
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
