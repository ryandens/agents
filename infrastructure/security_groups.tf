# Rules are declared as standalone resources rather than inline blocks so that
# individual rules can be changed without replacing the security group.

resource "aws_security_group" "ec2" {
  name        = "${var.project_name}-ec2"
  description = "EC2: HTTP/HTTPS inbound from internet, egress for SSM/ECR/updates"
  vpc_id      = aws_vpc.main.id

  lifecycle {
    create_before_destroy = true
  }
}

# --- EC2 ingress: internet-facing, terminated by Caddy on the instance ---

# Port 80 is required year-round, not just at first issuance: Let's Encrypt's
# HTTP-01 challenge is Caddy's fallback when TLS-ALPN-01 fails, and renewals run
# every ~60 days. Caddy redirects all other port 80 traffic to HTTPS.
resource "aws_vpc_security_group_ingress_rule" "ec2_http" {
  security_group_id = aws_security_group.ec2.id
  description       = "HTTP from internet (ACME HTTP-01 challenge and HTTPS redirect)"
  from_port         = 80
  to_port           = 80
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "ec2_https" {
  security_group_id = aws_security_group.ec2.id
  description       = "HTTPS from internet"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  cidr_ipv4         = "0.0.0.0/0"
}

# --- EC2 egress: all outbound for SSM, ECR pulls, and OS package updates ---

resource "aws_vpc_security_group_egress_rule" "ec2_all_outbound" {
  security_group_id = aws_security_group.ec2.id
  description       = "All outbound for SSM, ECR, and OS updates"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}
