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
#
# Two assertions, because there are two ways to open a hole and each is blind to the
# other. The first compares the group's live rule IDs against the exact pair Terraform
# manages, so an added rule fails even if someone deletes one of ours to keep the count
# at two. The second pins what the surviving ingress rule actually permits, since editing
# a rule in place changes neither its ID nor the count.
check "no_public_app_ingress" {
  data "aws_vpc_security_group_rules" "ec2_check" {
    filter {
      name   = "group-id"
      values = [aws_security_group.ec2.id]
    }
  }

  assert {
    condition = toset(data.aws_vpc_security_group_rules.ec2_check.ids) == toset([
      aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.security_group_rule_id,
      aws_vpc_security_group_egress_rule.ec2_all_outbound.security_group_rule_id,
    ])
    error_message = "EC2 security group holds rules Terraform does not manage: found ${jsonencode(data.aws_vpc_security_group_rules.ec2_check.ids)}, expected exactly the Tailscale WireGuard ingress and the all-traffic egress. The app must not be reachable off the tailnet."
  }

  assert {
    condition = alltrue([
      aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.ip_protocol == "udp",
      aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.from_port == 41641,
      aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.to_port == 41641,
    ])
    error_message = "The only ingress rule must stay udp/41641 (Tailscale WireGuard); it is now ${aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.ip_protocol}/${aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.from_port}-${aws_vpc_security_group_ingress_rule.ec2_tailscale_wireguard.to_port}. Any TCP port here is a public entry point to the app."
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
