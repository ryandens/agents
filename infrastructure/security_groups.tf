# The app has no public entry point: it is reachable only over the tailnet, and
# Tailscale builds that path with outbound connections. The one inbound rule below is
# Tailscale's own WireGuard port, which is an optimization rather than a requirement.

resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2"
  description = "EC2: no public ingress, Tailscale WireGuard only, egress for SSM/ECR/updates"
  vpc_id      = aws_vpc.main.id

  lifecycle {
    create_before_destroy = true
  }
}

# --- EC2 ingress: Tailscale only ---

# Lets peers reach the node directly instead of falling back to a DERP relay. The source
# is the internet because a peer's public address is wherever it happens to be that day;
# WireGuard authenticates every packet, so a sender without a tailnet key gets no further
# than a dropped packet. Removing this rule costs latency, not reachability.
resource "aws_vpc_security_group_ingress_rule" "ec2_tailscale_wireguard" {
  security_group_id = aws_security_group.ec2.id
  description       = "Tailscale WireGuard for direct peer connections"
  from_port         = 41641
  to_port           = 41641
  ip_protocol       = "udp"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- EC2 egress: all outbound for Tailscale, SSM, ECR pulls, and OS package updates ---

resource "aws_vpc_security_group_egress_rule" "ec2_all_outbound" {
  security_group_id = aws_security_group.ec2.id
  description       = "All outbound for Tailscale, SSM, ECR, and OS updates"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}


# --- Aurora: reachable from the app instance and from nothing else ---
#
# The instance's own group is unchanged. It already egresses everywhere, so granting it
# database access needs no rule on its side — which matters, because the
# `no_public_app_ingress` check in checks.tf asserts the EC2 group holds exactly the two
# rules Terraform manages and would fail if a third were added here.

resource "aws_security_group" "rds" {
  name        = "${var.project_name}-rds"
  description = "Aurora: Postgres from the app instance only, no egress"
  vpc_id      = aws_vpc.main.id

  lifecycle {
    create_before_destroy = true
  }
}

# Source is the instance's security group rather than a CIDR, so the rule keeps working
# if the instance is replaced and comes back on a different private address.
resource "aws_vpc_security_group_ingress_rule" "rds_from_ec2" {
  security_group_id            = aws_security_group.rds.id
  description                  = "Postgres from the app instance"
  from_port                    = 5432
  to_port                      = 5432
  ip_protocol                  = "tcp"
  referenced_security_group_id = aws_security_group.ec2.id
}

# No egress rules at all. Aurora only ever answers connections; anything it did try to
# open would be a sign something is wrong.
