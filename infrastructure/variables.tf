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
  description = "Image tag and digest to deploy, e.g. '0.1.0@sha256:abc123'. Tag is human-readable; digest pins the exact manifest. To upgrade: set to the new tag@digest and run terraform apply — the EC2 instance will be replaced. Note: /opt/agents/data resets on replacement until moved to EFS or a separate EBS volume."
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
    # them. Whitespace, quotes and backslashes are rejected because the joined value is
    # rendered into the systemd ExecStart line, where any of those could split it into
    # extra arguments or leave a quote unmatched — an unparseable unit that will not start.
    condition     = length(var.allowed_emails) > 0 && alltrue([for e in var.allowed_emails : can(regex("^[^@,\\s\"'\\\\]+@[^@,\\s\"'\\\\]+\\.[^@,\\s\"'\\\\]+$", e))])
    error_message = "allowed_emails must list at least one valid email address, containing no whitespace, commas, quotes or backslashes."
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
