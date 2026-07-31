# Aurora PostgreSQL — where the pantry lives.
#
# Serverless v2 with a floor of zero ACUs: the app is used a few times a day by one
# household, so the cluster spends most of its life paused and costs storage only. The
# price of that is a resume of roughly fifteen seconds on the first connection after an
# idle stretch, which is why db.py opens its pool with a generous timeout and why the
# boot health check in user_data.sh polls for two minutes rather than a few seconds.
#
# Set db_min_capacity above 0 to trade the money back for a cluster that is always warm.

resource "aws_db_subnet_group" "main" {
  name        = var.project_name
  description = "Private subnets for the ${var.project_name} Aurora cluster"
  subnet_ids  = aws_subnet.private[*].id
}

# No `special` characters, so the password can be dropped into the DATABASE_URL below
# without percent-encoding. 48 characters of alphanumeric is far more entropy than the
# punctuation would have added.
resource "random_password" "db" {
  length  = 48
  special = false
}

resource "aws_rds_cluster" "main" {
  cluster_identifier = var.project_name
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = var.db_engine_version

  database_name   = var.db_name
  master_username = var.db_username
  master_password = random_password.db.result
  port            = 5432

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  storage_encrypted = true

  serverlessv2_scaling_configuration {
    min_capacity             = var.db_min_capacity
    max_capacity             = var.db_max_capacity
    seconds_until_auto_pause = var.db_seconds_until_auto_pause
  }

  # A week of point-in-time recovery. The pantry is hand-entered data that exists
  # nowhere else, so the backup window matters more here than anywhere else in this
  # config; within it, any moment can be restored to a new cluster.
  backup_retention_period = 7
  copy_tags_to_snapshot   = true

  # Both deliberate, and both about the same thing: this holds the only copy of the
  # data. Deletion protection means a `terraform destroy` fails rather than silently
  # taking the pantry with it — clear the flag by hand first if that is really intended.
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${var.project_name}-final"

  # Postgres server logs to CloudWatch, which is the only way to see a connection being
  # refused or a query erroring — there is no other window into the cluster.
  enabled_cloudwatch_logs_exports = ["postgresql"]

  # Config changes take effect on apply rather than waiting for the maintenance window.
  # Nothing here is a change worth deferring, and deferring one hides whether it worked.
  apply_immediately = true
}

resource "aws_rds_cluster_instance" "main" {
  identifier         = "${var.project_name}-1"
  cluster_identifier = aws_rds_cluster.main.id
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.main.engine
  engine_version     = aws_rds_cluster.main.engine_version

  # In a private subnet with no route to the internet gateway, so this would be inert
  # either way; set explicitly so the intent is not left to the provider's default.
  publicly_accessible = false

  # Pinned like the app image and the base images: an upgrade is a reviewed change to
  # db_engine_version, not something that happens during a maintenance window while
  # nobody is looking. See that variable for how to find the current versions.
  auto_minor_version_upgrade = false

  performance_insights_enabled          = true
  performance_insights_retention_period = 7
}

# The connection string, assembled once here rather than in the systemd unit, so the
# unit does not have to know how Aurora names its endpoint. SecureString because it
# carries the password.
#
# sslmode=require encrypts the connection but does not verify the server certificate.
# verify-full would be better and needs the RDS CA bundle inside the image; until then
# the exposure is limited by the fact that the only path to the cluster is a private
# subnet with no internet route, reachable from one security group.
resource "aws_ssm_parameter" "database_url" {
  name        = "/agents/database-url"
  description = "Postgres DSN for the pantry. Read by agents.service at start."
  type        = "SecureString"
  value = format(
    "postgresql://%s:%s@%s:%s/%s?sslmode=require",
    var.db_username,
    random_password.db.result,
    aws_rds_cluster.main.endpoint,
    aws_rds_cluster.main.port,
    var.db_name,
  )
}
