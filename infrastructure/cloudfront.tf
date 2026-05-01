resource "aws_cloudfront_function" "rewrite" {
  name    = "${var.project_name}-rewrite"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOF
    async function handler(event) {
      const request = event.request;
      const uri = request.uri;
      if (uri.endsWith("/")) {
        request.uri += "index.html";
      } else if (!uri.includes(".")) {
        request.uri += "/index.html";
      }
      return request;
    }
  EOF
}

resource "aws_cloudfront_distribution" "main" {
  enabled             = true
  aliases             = ["agents.ryandens.com"]
  default_root_object = "index.html"
  price_class         = "PriceClass_100"

  # S3 origin — static frontend assets
  origin {
    domain_name              = aws_s3_bucket.frontend.bucket_regional_domain_name
    origin_id                = "s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.frontend.id
  }

  # ALB origin — API and OIDC callback via HTTP (within AWS network)
  origin {
    domain_name = aws_lb.main.dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  # /api/* → ALB, no caching, forward everything (cookies needed for OIDC session)
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  }

  # /oauth2/idpresponse → ALB, handled by the ALB OIDC authenticate action
  ordered_cache_behavior {
    path_pattern             = "/oauth2/idpresponse"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "https-only"
    allowed_methods          = ["GET", "HEAD"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # CachingDisabled
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3" # AllViewer
  }

  # /* → S3, cached, with path rewrite for Next.js static export
  default_cache_behavior {
    target_origin_id       = "s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "658327ea-f89d-4fab-a63d-7e88639e58f6" # CachingOptimized

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.rewrite.arn
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.main.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  custom_error_response {
    error_code         = 403
    response_code      = 404
    response_page_path = "/404/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 404
    response_page_path = "/404/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
}
