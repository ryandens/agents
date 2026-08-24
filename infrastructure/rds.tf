# Aurora PostgreSQL — where the pantry lives.
#
# Serverless v2 with a floor of zero ACUs: the app is used a few times a day by one
# household, so the cluster spends most of its life paused and costs storage only. The
# price of that is a resume of roughly fifteen seconds on the first connection after an
# idle stretch, which is why db.py opens its pool with a generous timeout and why the
# boot health check in user_data.sh polls for two minutes rather than a few seconds.
#
# The application pool must also be allowed to shrink to zero connections; otherwise
# one idle client pins Aurora at its active 0.5-ACU floor and this setting cannot pause.
# Set db_min_capacity above 0 to trade the money back for a cluster that is always warm.

resource "aws_db_subnet_group" "main" {
  name        = var.project_name
  description = "Private subnets for the ${var.project_name} Aurora cluster"
  subnet_ids  = aws_subnet.private[*].id
}

# Suffixes the final snapshot name. AWS refuses to create a snapshot whose name already
# exists, so a fixed name means the *second* destroy of a cluster fails outright with
# DBClusterSnapshotAlreadyExistsFault, with the first destroy's snapshot in the way.
#
# This covers the destroy-then-apply-again case, where state is gone and a fresh value is
# generated. It does not cover a cluster replaced in place, which keeps the same suffix —
# rare, and the failure is a refused destroy rather than lost data.
resource "random_id" "final_snapshot_suffix" {
  byte_length = 4
  keepers = {
    cluster_identifier = var.project_name
  }
}

resource "aws_rds_cluster" "main" {
  cluster_identifier = var.project_name
  engine             = "aurora-postgresql"
  engine_mode        = "provisioned"
  engine_version     = var.db_engine_version

  database_name   = var.db_name
  master_username = var.db_username
  port            = 5432

  # The app never uses this password — it authenticates with IAM (below), so the master
  # user exists only for administration. Handing it to RDS to manage means it is
  # generated in Secrets Manager, rotated by AWS on a schedule, and never passes through
  # Terraform: it is absent from the plan, from state, and from Parameter Store. The
  # instance role is not granted access to it, so nothing on the box can read it either.
  manage_master_user_password = true

  # What lets the instance connect with a signed token instead of a stored password.
  # Turning this off would leave the app with no way in at all.
  iam_database_authentication_enabled = true

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
  final_snapshot_identifier = "${var.project_name}-final-${random_id.final_snapshot_suffix.hex}"

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
# unit does not have to know how Aurora names its endpoint.
#
# A plain String, not a SecureString, and that is the point: it carries no password.
# The app authenticates as db_app_username with a token it signs at connect time from
# the instance profile, so this value is no more sensitive than a hostname.
#
# sslmode=require is mandatory for IAM auth — RDS rejects a token over a plaintext
# connection. It encrypts without verifying the server certificate; verify-full would
# be better and needs the RDS CA bundle inside the image. Until then the exposure is
# bounded by the only path to the cluster being a private subnet with no internet route,
# reachable from one security group.
resource "aws_ssm_parameter" "database_url" {
  name        = "/agents/database-url"
  description = "Passwordless Postgres DSN for the pantry. The app authenticates with an RDS IAM token."
  type        = "String"
  value = format(
    "postgresql://%s@%s:%s/%s?sslmode=require",
    var.db_app_username,
    aws_rds_cluster.main.endpoint,
    aws_rds_cluster.main.port,
    var.db_name,
  )
}

# Lets the instance role mint a token for exactly one database user on exactly one
# cluster. The resource path uses the cluster's *resource* id (cluster-ABC…), not its
# name, so the grant does not survive the cluster being destroyed and recreated — a
# replacement gets a new id, and this policy follows it.
#
# This is the whole of the credential story: no password is issued, stored or rotated,
# and revoking the app's access is deleting this statement.
resource "aws_iam_role_policy" "ec2_rds_connect" {
  name = "rds-iam-connect"
  role = aws_iam_role.ec2.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = "rds-db:connect"
      # Two roles, listed explicitly rather than wildcarded: the app's, which has DML
      # only, and the migrator's, which owns the schema. The instance can mint a token
      # for each because it runs both the app and the migrate step — what the split buys
      # is that the *app process* holds no DDL rights, so a bug or an injection in it
      # cannot reach the schema. Separating the two further would mean running migrations
      # from somewhere with different credentials entirely, such as CI.
      Resource = [
        "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_rds_cluster.main.cluster_resource_id}/${var.db_app_username}",
        "arn:aws:rds-db:${var.aws_region}:${data.aws_caller_identity.current.account_id}:dbuser:${aws_rds_cluster.main.cluster_resource_id}/${var.db_migrator_username}",
      ]
    }]
  })
}

# The migrator's DSN. Same cluster and database as the app's, different role — and, like
# the app's, no password: agents-migrate.service signs an IAM token for it at start.
resource "aws_ssm_parameter" "migrator_database_url" {
  name        = "/agents/migrator-database-url"
  description = "Passwordless Postgres DSN used by agents-migrate.service. Connects as the schema-owning role, which the app deliberately is not."
  type        = "String"
  value = format(
    "postgresql://%s@%s:%s/%s?sslmode=require",
    var.db_migrator_username,
    aws_rds_cluster.main.endpoint,
    aws_rds_cluster.main.port,
    var.db_name,
  )
}
