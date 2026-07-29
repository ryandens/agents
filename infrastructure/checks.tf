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

# The instance sits in a public subnet for outbound reachability, so nothing structural
# stops someone opening a port on it by hand. A plan will not catch that — an
# out-of-band rule is not in state, so there is no managed resource to show as drifted.
# Counting rules does catch it. Two is the whole intended set: udp/41641 in, everything
# out. Bump the number here only alongside a rule this file can point at.
check "no_public_app_ingress" {
  data "aws_vpc_security_group_rules" "ec2_check" {
    filter {
      name   = "group-id"
      values = [aws_security_group.ec2.id]
    }
  }

  assert {
    condition     = length(data.aws_vpc_security_group_rules.ec2_check.ids) == 2
    error_message = "EC2 security group has ${length(data.aws_vpc_security_group_rules.ec2_check.ids)} rules; expected exactly 2 (Tailscale WireGuard in, all out). The app must not be reachable off the tailnet."
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
