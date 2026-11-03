terraform {
  required_version = ">= 1.10"

  # The state lives in S3, in the bucket made by infra/state, which also writes the settings
  # of this backend into backend.hcl. use_lockfile: a lock object next to the state stops
  # two runs from changing the cluster at the same time
  backend "s3" {}

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
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
  # internet would be used (and paid for) by strangers, so only my IP gets in.
  # Ollama (11434), Grafana and Prometheus have no rule at all: they are reached
  # from inside the node, or through an SSH tunnel
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

# The identity of the node on AWS. It may only register with Session Manager, which gives
# a shell from the AWS console when SSH does not work. It needs nothing else from AWS
resource "aws_iam_role" "node" {
  name = "devops-lab-node"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.node.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "node" {
  name = "devops-lab-node"
  role = aws_iam_role.node.name
}

resource "aws_instance" "k3s" {
  ami                         = nonsensitive(data.aws_ssm_parameter.ubuntu.value)
  instance_type               = var.instance_type
  key_name                    = aws_key_pair.lab.key_name
  vpc_security_group_ids      = [aws_security_group.k3s.id]
  associate_public_ip_address = true
  iam_instance_profile        = aws_iam_instance_profile.node.name

  user_data = templatefile("${path.module}/user_data.sh", {
    chat_model  = var.chat_model
    embed_model = var.embed_model
  })
  # the boot script runs only once: a new script needs a new node to take effect
  user_data_replace_on_change = true

  # T instances default to "unlimited" CPU credits, which bill extra when the CPU bursts
  # for long. Other families have no credits, and AWS would refuse the setting
  dynamic "credit_specification" {
    for_each = startswith(var.instance_type, "t") ? [1] : []
    content {
      cpu_credits = "standard"
    }
  }

  root_block_device {
    volume_type = "gp3"
    # the images, the models (about 3 GB) and three days of Prometheus data
    volume_size = 30
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
