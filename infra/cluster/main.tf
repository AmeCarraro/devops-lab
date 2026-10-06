terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project = "devops-lab"
    }
  }
}

data "aws_vpc" "default" {
  default = true
}

# Latest Ubuntu 24.04 AMI, published by Canonical as a public SSM parameter
data "aws_ssm_parameter" "ubuntu" {
  name = "/aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id"
}

resource "aws_key_pair" "lab" {
  key_name   = "devops-lab"
  public_key = file(pathexpand(var.ssh_public_key_path))
}

resource "aws_security_group" "k3s" {
  name        = "devops-lab-k3s"
  description = "SSH and HTTP from my IP only"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "SSH only from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  # /ask and /mcp have no authentication yet: an LLM endpoint open to the
  # internet would be used (and paid for) by strangers, so only my IP gets in
  ingress {
    description = "HTTP to the app (Traefik ingress), only from my IP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.my_ip_cidr]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "k3s" {
  ami                         = nonsensitive(data.aws_ssm_parameter.ubuntu.value)
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.lab.key_name
  vpc_security_group_ids      = [aws_security_group.k3s.id]
  associate_public_ip_address = true
  user_data                   = file("${path.module}/user_data.sh")

  # T3 defaults to "unlimited", which bills extra when the CPU bursts for long
  credit_specification {
    cpu_credits = "standard"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 20
  }

  metadata_options {
    http_tokens = "required"
  }

  tags = {
    Name = "devops-lab-k3s"
  }

  lifecycle {
    # a newer AMI must not recreate the node on the next apply
    ignore_changes = [ami]
  }
}
