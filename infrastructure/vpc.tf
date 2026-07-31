data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  # One AZ. The ALB was the only thing that needed two, and a single EC2 instance cannot
  # span them; the second subnet sat empty. Widen the slice and add a CIDR to go back.
  azs            = slice(data.aws_availability_zones.available.names, 0, 1)
  public_subnets = ["10.0.1.0/24"]

  # Aurora is the exception to the single-AZ rule: RDS will not accept a DB subnet group
  # covering fewer than two availability zones, even for a one-instance cluster. The
  # second subnet holds nothing today — it exists so the subnet group is valid, and so a
  # failover has somewhere to land if a reader is ever added.
  db_azs          = slice(data.aws_availability_zones.available.names, 0, 2)
  private_subnets = ["10.0.11.0/24", "10.0.12.0/24"]
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


# --- Private subnets: the database, and nothing else ---
#
# Aurora needs no route off the VPC — it never initiates a connection and is only ever
# reached from the instance — so these subnets get a route table with no routes at all.
# That is not merely tidy: with no internet gateway route and no NAT, a database that
# somehow ended up with publicly_accessible = true still would not be reachable from
# outside the VPC. Skipping the NAT gateway also saves its hourly charge.

resource "aws_subnet" "private" {
  count             = length(local.db_azs)
  vpc_id            = aws_vpc.main.id
  cidr_block        = local.private_subnets[count.index]
  availability_zone = local.db_azs[count.index]

  map_public_ip_on_launch = false
}

# No route blocks: the implicit local route is the only way in or out.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table_association" "private" {
  count          = length(local.db_azs)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
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
