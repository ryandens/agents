variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for resource naming and tagging"
  type        = string
  default     = "agents"
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "ec2_instance_type" {
  description = "EC2 instance type (must be ARM/Graviton-based, e.g. t4g.*)"
  type        = string
  default     = "t4g.micro"

  validation {
    condition     = can(regex("^(t4g|m7g|m8g|c7g|c8g|r7g|r8g|x2g|hpc7g|im4gn|is4gen)\\.", var.ec2_instance_type))
    error_message = "ec2_instance_type must be an ARM/Graviton family (t4g, m7g, c7g, r7g, …)."
  }
}

variable "app_version" {
  description = "Image tag and digest to deploy, e.g. '0.1.0@sha256:abc123'. Tag is human-readable; digest pins the exact manifest. To upgrade: set the new tag@digest, run terraform apply (which updates the SSM parameter in place), then restart agents.service — `just deploy` does both. The instance is not replaced, so the app is down only for the few seconds the container takes to restart."
  type        = string
}

variable "anthropic_api_key" {
  description = "Anthropic API key for the Kitchen Agent backend"
  type        = string
  sensitive   = true
}

variable "google_client_id" {
  description = "Google OAuth client ID for the backend's OIDC authorization code flow"
  type        = string
}

variable "google_client_secret" {
  description = "Google OAuth client secret, used to exchange the authorization code for an ID token"
  type        = string
  sensitive   = true
}

variable "allowed_emails" {
  description = "Google accounts permitted to sign in. Google does not enforce its OAuth test-user list for openid/email/profile apps, so this list is the only thing restricting access — an empty list locks everyone out."
  type        = list(string)

  validation {
    # Commas are rejected because the list is joined on them and the backend splits on
    # them. Whitespace is rejected because the joined value becomes one line of a docker
    # --env-file, where an embedded newline would inject a second variable outright.
    # Quotes and backslashes stopped being load-bearing when this moved out of the unit's
    # ExecStart line into Parameter Store, but they have no business in an address and
    # excluding them keeps the value safe to pass through a shell.
    condition     = length(var.allowed_emails) > 0 && alltrue([for e in var.allowed_emails : can(regex("^[^@,\\s\"'\\\\]+@[^@,\\s\"'\\\\]+\\.[^@,\\s\"'\\\\]+$", e))])
    error_message = "allowed_emails must list at least one valid email address, containing no whitespace, commas, quotes or backslashes."
  }
}

variable "allowed_service_accounts" {
  description = "Google service accounts permitted to call the API with a bearer ID token, for callers that have no browser to sign in with. Separate from allowed_emails so machine access and human sign-in are granted independently. Empty — the default — disables bearer auth entirely."
  type        = list(string)
  default     = []

  validation {
    # Same formatting rules as allowed_emails, for the same --env-file reason, narrowed
    # further to the *.iam.gserviceaccount.com form. A human address put here by mistake
    # therefore fails at plan time rather than silently becoming a credential that never
    # works — only a service account can mint a token for a target audience.
    condition     = alltrue([for s in var.allowed_service_accounts : can(regex("^[^@,\\s\"'\\\\]+@[^@,\\s\"'\\\\]+\\.iam\\.gserviceaccount\\.com$", s))])
    error_message = "allowed_service_accounts must list only *.iam.gserviceaccount.com addresses, containing no whitespace, commas, quotes or backslashes."
  }
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key used to join the tailnet at boot. Must be reusable, ephemeral and pre-approved; generate at https://login.tailscale.com/admin/settings/keys. Ephemeral is what lets a retired instance delete its node and free the machine name for its replacement. Keys expire (90 days max), and the instance re-registers on every boot, so rotate this before then or a reboot will leave the app unreachable."
  type        = string
  sensitive   = true

  validation {
    condition     = startswith(var.tailscale_auth_key, "tskey-auth-")
    error_message = "tailscale_auth_key must be an auth key (starts with 'tskey-auth-'), not an API or OAuth key."
  }
}

variable "tailscale_hostname" {
  description = "MagicDNS hostname for the instance on the tailnet"
  type        = string
  default     = "agents"

  validation {
    # A single DNS label, which is stricter than it looks like it needs to be. The value
    # is interpolated into local.app_url, where a '/' would silently move the OAuth
    # redirect to a different origin, and into an unquoted --hostname= argument in the
    # systemd unit, where whitespace would split it into a second argument.
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.tailscale_hostname))
    error_message = "tailscale_hostname must be a single lowercase DNS label (letters, digits and hyphens, starting and ending alphanumeric, at most 63 characters)."
  }
}

variable "tailscale_tailnet" {
  description = "Tailnet DNS name, e.g. 'tail1a2b3c.ts.net' — shown on the DNS page of the Tailscale admin console. Composes the app's only origin, so it must match the tailnet the auth key belongs to."
  type        = string

  validation {
    # Bare DNS name, not a URL: a suffix check alone would accept
    # 'https://example.ts.net' and yield 'https://agents.https://example.ts.net'.
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*\\.ts\\.net$", var.tailscale_tailnet))
    error_message = "tailscale_tailnet must be a bare DNS name ending in '.ts.net' (e.g. 'tail1a2b3c.ts.net') — no scheme, path or trailing dot."
  }
}

# The app has exactly one origin now that it is reachable only over the tailnet, so it is
# derived rather than configured: a separate app_base_url variable could silently drift
# from the node's real MagicDNS name, and Google's redirect-URI match is exact.
locals {
  app_url = "https://${var.tailscale_hostname}.${var.tailscale_tailnet}"

  # Fixed name for a parameter that is only sometimes created. The systemd unit is
  # rendered with this rather than with the resource's attribute so that adding the first
  # service account — or removing the last — leaves user_data untouched.
  allowed_service_accounts_parameter = "/agents/allowed-service-accounts"
}

variable "app_port" {
  description = "Port the application listens on"
  type        = number
  default     = 8080

  validation {
    condition     = var.app_port >= 1024 && var.app_port <= 65535
    error_message = "app_port must be an unprivileged port (1024–65535)."
  }
}

# ── Database ──────────────────────────────────────────────────────────────────

variable "db_name" {
  description = "Name of the database inside the Aurora cluster."
  type        = string
  default     = "agents"

  validation {
    # Postgres identifier rules, and the value is interpolated into a DSN where a '/' or
    # '?' would silently move the path or start a query string.
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.db_name))
    error_message = "db_name must be a lowercase Postgres identifier: letters, digits and underscores, not starting with a digit."
  }
}

variable "db_app_username" {
  description = "Database role the app connects as, using an RDS IAM token rather than a password. Separate from the master user because a role granted rds_iam can only authenticate by token — keeping the two apart leaves the master usable for administration. Created by `just db-bootstrap`, which is a one-time step after the first apply; the IAM policy grants rds-db:connect for this name specifically, so changing it means re-running that bootstrap."
  type        = string
  default     = "agents_app"

  validation {
    # Postgres identifier rules. Also interpolated into an IAM resource ARN, where a
    # '/' or a wildcard character would widen the grant beyond the single user intended.
    condition     = can(regex("^[a-z_][a-z0-9_]{0,62}$", var.db_app_username))
    error_message = "db_app_username must be a lowercase Postgres identifier: letters, digits and underscores, not starting with a digit."
  }
}

variable "db_username" {
  description = "Master username on the Aurora cluster, for administration only — the app connects as db_app_username with an IAM token. Its password is generated and rotated by AWS in Secrets Manager and never passes through Terraform."
  type        = string
  default     = "agents"

  validation {
    # 'rds_superuser' and friends are reserved by RDS, and the same DSN-safety rules as
    # db_name apply since this is interpolated into the userinfo part of the URL.
    condition     = can(regex("^[a-z][a-z0-9]{0,62}$", var.db_username)) && !contains(["rdsadmin", "admin", "postgres"], var.db_username)
    error_message = "db_username must start with a letter, contain only lowercase letters and digits, and must not be a name RDS reserves ('rdsadmin', 'admin', 'postgres')."
  }
}

variable "db_engine_version" {
  description = "Aurora PostgreSQL version. Pinned rather than auto-upgraded, so a minor bump is a reviewed change like the app image is. List what is available with: aws rds describe-db-engine-versions --engine aurora-postgresql --query 'DBEngineVersions[].EngineVersion'."
  type        = string
  default     = "17.4"

  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+$", var.db_engine_version))
    error_message = "db_engine_version must be a major.minor Aurora PostgreSQL version, e.g. '17.4'."
  }
}

variable "db_min_capacity" {
  description = "Aurora Serverless v2 floor, in ACUs. 0 lets the cluster pause when idle and is what makes this affordable for a household-sized app; the cost is roughly fifteen seconds to resume on the first connection afterwards. Set 0.5 or more to keep it always warm."
  type        = number
  default     = 0

  validation {
    condition     = var.db_min_capacity == 0 || (var.db_min_capacity >= 0.5 && var.db_min_capacity <= 256)
    error_message = "db_min_capacity must be 0 (auto-pause) or between 0.5 and 256 ACUs."
  }
}

variable "db_max_capacity" {
  description = "Aurora Serverless v2 ceiling, in ACUs. The workload is a handful of single-row queries, so this is a runaway-cost backstop rather than a target."
  type        = number
  default     = 4

  validation {
    condition     = var.db_max_capacity >= 1 && var.db_max_capacity <= 256 && var.db_max_capacity >= var.db_min_capacity
    error_message = "db_max_capacity must be between 1 and 256 ACUs, and not below db_min_capacity."
  }
}

variable "db_seconds_until_auto_pause" {
  description = "How long the cluster stays idle before pausing, when db_min_capacity is 0. Ignored otherwise. An hour keeps a day's normal use on a warm cluster while still pausing overnight."
  type        = number
  default     = 3600

  validation {
    condition     = var.db_seconds_until_auto_pause >= 300 && var.db_seconds_until_auto_pause <= 86400
    error_message = "db_seconds_until_auto_pause must be between 300 and 86400 seconds — the range Aurora accepts."
  }
}
