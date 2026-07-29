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
        Effect = "Allow"
        Action = "ssm:GetParameter"
        Resource = [
          aws_ssm_parameter.anthropic_api_key.arn,
          aws_ssm_parameter.google_client_secret.arn,
          aws_ssm_parameter.session_secret.arn,
        ]
      },
    ]
  })
}

resource "aws_ssm_parameter" "anthropic_api_key" {
  name  = "/agents/anthropic-api-key"
  type  = "SecureString"
  value = var.anthropic_api_key
}

# Secrets go through SSM rather than the systemd unit, because that unit is rendered
# into EC2 user data — readable by anyone with ec2:DescribeInstances and by any process
# on the box via IMDS. The client ID stays inline since it is public by design.
resource "aws_ssm_parameter" "google_client_secret" {
  name  = "/agents/google-client-secret"
  type  = "SecureString"
  value = var.google_client_secret
}

# Signs session cookies. Generated rather than supplied: nothing outside the instance
# needs to know it, and rotating it just signs everyone out. Kept in state, so treat the
# state file as sensitive.
resource "random_password" "session_secret" {
  length  = 48
  special = false
}

resource "aws_ssm_parameter" "session_secret" {
  name  = "/agents/session-secret"
  type  = "SecureString"
  value = random_password.session_secret.result
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2"
  role = aws_iam_role.ec2.name
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023_arm64.id
  instance_type               = var.ec2_instance_type
  subnet_id                   = aws_subnet.public[0].id
  iam_instance_profile        = aws_iam_instance_profile.ec2.name
  vpc_security_group_ids      = [aws_security_group.ec2.id]
  associate_public_ip_address = true # needed for SSM via internet; replace with VPC endpoints to remove

  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/files/user_data.sh", {
    service_content = templatefile("${path.module}/files/agents.service", {
      aws_region                    = var.aws_region
      ecr_registry                  = split("/", aws_ecr_repository.main.repository_url)[0]
      ecr_image                     = "${aws_ecr_repository.main.repository_url}:${var.app_version}"
      ssm_parameter_name            = aws_ssm_parameter.anthropic_api_key.name
      client_secret_parameter_name  = aws_ssm_parameter.google_client_secret.name
      session_secret_parameter_name = aws_ssm_parameter.session_secret.name
      google_client_id              = var.google_client_id
      app_base_url                  = var.app_base_url
      allowed_emails                = join(",", var.allowed_emails)
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
