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
