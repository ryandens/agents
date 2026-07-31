output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "Public subnet IDs"
  value       = aws_subnet.public[*].id
}

output "ecr_repository_url" {
  description = "ECR repository URL for pushing Docker images"
  value       = aws_ecr_repository.main.repository_url
}

output "app_url" {
  description = "Where the app lives — reachable only from a device on the tailnet, serving both the frontend and the API. Also the OAuth redirect origin the instance is configured with."
  value       = local.app_url
}

output "ec2_instance_id" {
  description = "EC2 instance ID — connect with: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "aws_region" {
  description = "Region everything lives in. Exported so `just restart` targets the same one Terraform used, rather than whatever the caller's AWS CLI happens to default to."
  value       = var.aws_region
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions ECR push — set as the AWS_ROLE_ARN repository secret"
  value       = aws_iam_role.github_actions_ecr_push.arn
}

output "db_cluster_endpoint" {
  description = "Aurora writer endpoint. Reachable only from inside the VPC — connect through the instance with `just ssh`, not from a laptop."
  value       = aws_rds_cluster.main.endpoint
}

output "db_name" {
  description = "Database the app connects to on that cluster."
  value       = aws_rds_cluster.main.database_name
}
