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
    condition     = length(var.allowed_emails) > 0
    error_message = "allowed_emails must list at least one address, or nobody can sign in."
  }
}

variable "app_base_url" {
  description = "Public origin of the app. Google redirects back to <app_base_url>/api/auth/callback, which must be registered as an authorized redirect URI on the OAuth client."
  type        = string
  default     = "https://agents.ryandens.com"

  validation {
    condition     = startswith(var.app_base_url, "https://")
    error_message = "app_base_url must be https, otherwise the session cookie's Secure flag is dropped."
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
