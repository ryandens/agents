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

output "api_public_ip" {
  description = "Elastic IP serving the API — the A record for the API domain resolves here"
  value       = aws_eip.app.public_ip
}

output "ec2_instance_id" {
  description = "EC2 instance ID — connect with: aws ssm start-session --target <id>"
  value       = aws_instance.app.id
}

output "github_actions_role_arn" {
  description = "IAM role ARN for GitHub Actions ECR push — set as the AWS_ROLE_ARN repository secret"
  value       = aws_iam_role.github_actions_ecr_push.arn
}

output "s3_frontend_bucket" {
  description = "S3 bucket name for frontend static assets — set as S3_FRONTEND_BUCKET Actions variable"
  value       = aws_s3_bucket.frontend.id
}

output "cloudfront_distribution_id" {
  description = "CloudFront distribution ID — set as CLOUDFRONT_DISTRIBUTION_ID Actions variable"
  value       = aws_cloudfront_distribution.main.id
}
