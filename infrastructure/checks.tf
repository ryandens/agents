# check blocks run after every apply and plan; failures are warnings, not errors,
# so they surface drift without blocking normal operations.

check "ec2_running" {
  data "aws_instance" "app_check" {
    instance_id = aws_instance.app.id
  }

  assert {
    condition     = data.aws_instance.app_check.instance_state == "running"
    error_message = "EC2 instance ${aws_instance.app.id} is not in 'running' state."
  }
}

check "alb_active" {
  data "aws_lb" "main_check" {
    arn = aws_lb.main.arn
  }

  assert {
    condition     = data.aws_lb.main_check.internal == false
    error_message = "ALB must be internet-facing; got internal=true."
  }
}

check "ecr_scanning_enabled" {
  data "aws_ecr_repository" "main_check" {
    name = aws_ecr_repository.main.name
  }

  assert {
    condition     = data.aws_ecr_repository.main_check.image_scanning_configuration[0].scan_on_push == true
    error_message = "ECR repository must have scan_on_push enabled."
  }
}
