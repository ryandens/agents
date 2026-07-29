data "aws_ami" "al2023_arm64" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023*-arm64"]
  }

  filter {
    name   = "architecture"
    values = ["arm64"]
  }

  filter {
    name   = "state"
    values = ["available"]
  }
}

resource "aws_iam_role" "ec2" {
  name = "${var.project_name}-ec2"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ec2.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "ec2_agents" {
  name = "ecr-pull-ssm-read"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
        ]
        Resource = aws_ecr_repository.main.arn
      },
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = aws_ssm_parameter.anthropic_api_key.arn
      },
    ]
  })
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/agents/anthropic-api-key"
  type  = "SecureString"
  value = var.anthropic_api_key
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2"
  role = aws_iam_role.ec2.name
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023_arm64.id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.public[0].id
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids = [aws_security_group.ec2.id]

  # An auto-assigned public IP is still required: user_data pulls from ECR and
  # registers with SSM before Terraform attaches the Elastic IP below. The auto
  # IP is released once the EIP is associated, so only one address is billed.
  associate_public_ip_address = true

  user_data_replace_on_change = true

  # Caddy requests a certificate as soon as it starts, and Let's Encrypt caps
  # failed validations at 5 per hostname per hour. Creating the A record first
  # keeps boot-time retries from burning through that budget.
  depends_on = [aws_route53_record.api]

  user_data = templatefile("${path.module}/files/user_data.sh", {
    service_content = templatefile("${path.module}/files/agents.service", {
      aws_region         = var.aws_region
      ecr_registry       = split("/", aws_ecr_repository.main.repository_url)[0]
      ecr_image          = "${aws_ecr_repository.main.repository_url}:${var.app_version}"
      ssm_parameter_name = aws_ssm_parameter.anthropic_api_key.name
      google_client_id   = var.google_client_id
    })

    caddy_service_content = templatefile("${path.module}/files/caddy.service", {
      caddy_image = var.caddy_image
    })

    caddyfile_content = templatefile("${path.module}/files/Caddyfile", {
      api_domain = var.api_domain
      acme_email = var.acme_email
      app_port   = var.app_port
    })
  })

  # IMDSv2 enforced: prevents SSRF attacks from stealing instance credentials via metadata API
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 30
    encrypted   = true
  }

  monitoring = true

  lifecycle {
    precondition {
      condition     = data.aws_ami.al2023_arm64.architecture == "arm64"
      error_message = "Resolved AMI architecture is '${data.aws_ami.al2023_arm64.architecture}'; expected arm64 for Graviton instance types."
    }
  }
}

# Declared separately from the instance so the address survives the instance
# replacement that user_data_replace_on_change triggers on every version bump.
# The A record for var.api_domain points here, so it must not change.
resource "aws_eip" "app" {
  domain = "vpc"
}

resource "aws_eip_association" "app" {
  instance_id   = aws_instance.app.id
  allocation_id = aws_eip.app.id
}
