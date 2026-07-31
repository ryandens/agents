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
        # The service-account list is conditional, so it is appended by splat rather than
        # named — an empty list contributes nothing instead of a dangling reference.
        Resource = concat([
          aws_ssm_parameter.anthropic_api_key.arn,
          aws_ssm_parameter.google_client_secret.arn,
          aws_ssm_parameter.session_secret.arn,
          aws_ssm_parameter.tailscale_auth_key.arn,
          aws_ssm_parameter.app_version.arn,
          aws_ssm_parameter.google_client_id.arn,
          aws_ssm_parameter.app_base_url.arn,
          aws_ssm_parameter.allowed_emails.arn,
          # Where the database is: endpoint, port, database name, and the role to
          # connect as. No credential — the DSN has no password in it, which is why
          # rds.tf declares this parameter a String rather than a SecureString.
          #
          # Reading it grants no access to the data. That comes from the
          # rds-db:connect policy in rds.tf, which lets the instance sign its own
          # short-lived token, plus the security group in security_groups.tf. Without
          # this parameter the app would not know where to connect; with it and nothing
          # else, it still could not get in.
          aws_ssm_parameter.database_url.arn,
        ], aws_ssm_parameter.allowed_service_accounts[*].arn)
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

# Read at every boot to join the tailnet, so the key must be reusable, ephemeral and
# pre-approved. Ephemeral is what lets the unit's ExecStop delete the node instead of just
# disconnecting it, which is the only way the replacement instance can reclaim the machine
# name. The instance therefore has no durable tailnet identity — it re-registers each boot,
# and the key has to still be valid when it does.
resource "aws_ssm_parameter" "tailscale_auth_key" {
  name  = "/agents/tailscale-auth-key"
  type  = "SecureString"
  value = var.tailscale_auth_key
}

# ── Runtime configuration ─────────────────────────────────────────────────────
#
# These are not secrets; they live in Parameter Store for a different reason. Anything
# rendered into the systemd unit lands in user_data, and user_data_replace_on_change
# turns every edit into a new EC2 instance. Held here instead, the unit references only
# the (fixed) parameter names, so changing a value is an in-place SSM update followed by
# `systemctl restart agents.service` — no replacement, so the app is down only for the
# few seconds the container takes to come back. The pantry is in Aurora and unaffected
# either way; keeping the instance is now about downtime rather than about data.

resource "aws_ssm_parameter" "app_version" {
  name        = "/agents/app-version"
  description = "Image tag@digest the unit pulls on start. Restart agents.service to roll out a change."
  type        = "String"
  value       = var.app_version
}

# Public by design — it ships in the OAuth redirect — so String, not SecureString. Its
# partner secret stays in google_client_secret above.
resource "aws_ssm_parameter" "google_client_id" {
  name  = "/agents/google-client-id"
  type  = "String"
  value = var.google_client_id
}

resource "aws_ssm_parameter" "app_base_url" {
  name        = "/agents/app-base-url"
  description = "Public origin, and the audience a service account must mint its ID token for."
  type        = "String"
  value       = local.app_url
}

resource "aws_ssm_parameter" "allowed_emails" {
  name        = "/agents/allowed-emails"
  description = "Comma-separated addresses permitted to sign in. The only thing restricting access."
  type        = "String"
  value       = join(",", var.allowed_emails)
}

# Created only when non-empty: SSM rejects a zero-length value, and empty is both the
# default and the meaningful "bearer auth is off" state. The unit tolerates the parameter
# being absent and treats that as empty, so deleting every entry here turns machine
# access off on the next restart rather than failing the start.
resource "aws_ssm_parameter" "allowed_service_accounts" {
  count = length(var.allowed_service_accounts) > 0 ? 1 : 0

  name        = local.allowed_service_accounts_parameter
  description = "Comma-separated service accounts permitted to call the API with a bearer ID token."
  type        = "String"
  value       = join(",", var.allowed_service_accounts)
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
  associate_public_ip_address = true # outbound only, for Tailscale/SSM/ECR; no inbound TCP is open

  user_data_replace_on_change = true

  user_data = templatefile("${path.module}/files/user_data.sh", {
    app_port = var.app_port

    # Hash of secrets included to trigger instance replacement when they rotate.
    # The hash is embedded in user_data; when it changes, user_data_replace_on_change kicks in.
    google_client_secret_hash = sha256(aws_ssm_parameter.google_client_secret.value)
    session_secret_hash       = sha256(aws_ssm_parameter.session_secret.value)

    # Parameter *names* only. Every value the unit needs is fetched at start, so this
    # block — and therefore user_data — stays byte-identical across a release. The
    # service-account name comes from a local rather than the resource, because that
    # resource is conditional: referencing it would make user_data change (and replace
    # the instance) the first time someone adds or removes a service account.
    service_content = templatefile("${path.module}/files/agents.service", {
      aws_region                              = var.aws_region
      app_port                                = var.app_port
      ecr_registry                            = split("/", aws_ecr_repository.main.repository_url)[0]
      ecr_repository_url                      = aws_ecr_repository.main.repository_url
      ssm_parameter_name                      = aws_ssm_parameter.anthropic_api_key.name
      client_secret_parameter_name            = aws_ssm_parameter.google_client_secret.name
      session_secret_parameter_name           = aws_ssm_parameter.session_secret.name
      app_version_parameter_name              = aws_ssm_parameter.app_version.name
      client_id_parameter_name                = aws_ssm_parameter.google_client_id.name
      app_base_url_parameter_name             = aws_ssm_parameter.app_base_url.name
      allowed_emails_parameter_name           = aws_ssm_parameter.allowed_emails.name
      allowed_service_accounts_parameter_name = local.allowed_service_accounts_parameter
      database_url_parameter_name             = aws_ssm_parameter.database_url.name
    })

    tailscale_service_content = templatefile("${path.module}/files/tailscale.service", {
      aws_region         = var.aws_region
      app_port           = var.app_port
      ssm_parameter_name = aws_ssm_parameter.tailscale_auth_key.name
      tailscale_hostname = var.tailscale_hostname
    })
  })

  # IMDSv2 enforced: prevents SSRF attacks from stealing instance credentials via metadata API
  metadata_options {
    http_endpoint = "enabled"
    http_tokens   = "required"

    # 2, not 1, because the app runs in a container and mints its own RDS IAM tokens.
    # Docker's bridge network puts one extra hop between the process and IMDS, so a
    # limit of 1 silently blocks the container from ever reading instance credentials —
    # the app would come up and fail every database connection.
    #
    # The cost is that any container on this host can reach IMDS, not just this one.
    # That is acceptable here because the host runs exactly one workload; it would not
    # be on a box running untrusted or multi-tenant containers.
    http_put_response_hop_limit = 2
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
