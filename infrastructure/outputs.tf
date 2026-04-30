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

output "alb_dns_name" {
  description = "ALB DNS name — point your domain's CNAME record here"
  value       = aws_lb.main.dns_name
}

output "ec2_instance_id" {
  description = "EC2 instance ID — connect with: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions ECR push — set as the AWS_ROLE_ARN repository secret"
  value       = aws_iam_role.github_actions_ecr_push.arn
}
