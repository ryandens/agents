data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs            = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets = ["10.0.1.0/24", "10.0.2.0/24"]
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  count             = length(local.azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.public_subnets[count.index]
  availability_zone = local.azs[count.index]

  # Disabled; only resources that explicitly opt in receive a public IP
  map_public_ip_on_launch = false
}


resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = length(local.azs)
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}


# Take ownership of the VPC default route table so it has no routes and
# acts as a dead-end catch-all for any subnet without an explicit association.
resource "aws_default_route_table" "default" {
  default_route_table_id = aws_vpc.main.default_route_table_id
}

# Lock down the default security group to no rules. Any resource accidentally
# assigned the default SG (e.g. by omitting vpc_security_group_ids) will have
# zero connectivity rather than broad implicit access.
resource "aws_default_security_group" "default" {
  vpc_id = aws_vpc.main.id
}
