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
  description = "Google OAuth client ID for verifying ID tokens in the backend"
  type        = string
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key used to join the tailnet at boot. Must be reusable and pre-approved; generate at https://login.tailscale.com/admin/settings/keys. Keys expire (90 days max), so rotate this before the instance is next replaced."
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
}

variable "tailscale_tailnet" {
  description = "Tailnet DNS name, e.g. 'tail1a2b3c.ts.net' — shown on the DNS page of the Tailscale admin console. Used only to compose the app_url output."
  type        = string

  validation {
    condition     = endswith(var.tailscale_tailnet, ".ts.net")
    error_message = "tailscale_tailnet must be the tailnet's DNS name ending in '.ts.net'."
  }
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
