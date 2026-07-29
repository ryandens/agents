data "aws_route53_zone" "main" {
  name         = "ryandens.com"
  private_zone = false
}

resource "aws_acm_certificate" "main" {
  domain_name               = "agents.ryandens.com"
  subject_alternative_names = ["api.agents.ryandens.com"]
  validation_method         = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.main.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 60
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# agents.ryandens.com → CloudFront (frontend static assets)
resource "aws_route53_record" "app" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "agents.ryandens.com"
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.main.domain_name
    zone_id                = aws_cloudfront_distribution.main.hosted_zone_id
    evaluate_target_health = false
  }
}

# api.agents.ryandens.com → EC2 Elastic IP (backend API, bypasses CloudFront for
# streaming). Caddy on the instance terminates TLS with a Let's Encrypt cert; the
# ACM cert above covers this name only for CloudFront's benefit and is unused here.
#
# This record must resolve before the instance first boots, since Caddy cannot
# complete an ACME challenge until the name points at it.
resource "aws_route53_record" "api" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = var.api_domain
  type    = "A"
  ttl     = 60
  records = [aws_eip.app.public_ip]
}
