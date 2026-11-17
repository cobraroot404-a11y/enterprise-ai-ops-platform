# Illustrative AWS blueprint (docs/architecture/cloud-portability.md). NOT validated, NOT applied, NOT a deployment.
# It sketches the network, the private PostgreSQL instance and the secret containers the platform would need. Container images,
# ECS services, the load balancer, the WAF and the egress proxy are described in the document and deliberately not written here.

data "aws_availability_zones" "available" {
  state = "available"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = merge(var.tags, { Name = "${var.name_prefix}-vpc" })
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = data.aws_availability_zones.available.names[count.index]
  tags              = merge(var.tags, { Name = "${var.name_prefix}-private-${count.index}" })
}

resource "aws_security_group" "app" {
  name        = "${var.name_prefix}-app"
  description = "API and worker tasks"
  vpc_id      = aws_vpc.this.id
  tags        = var.tags
}

resource "aws_security_group" "db" {
  name        = "${var.name_prefix}-db"
  description = "PostgreSQL: reachable only from the application tasks"
  vpc_id      = aws_vpc.this.id
  tags        = var.tags

  ingress {
    description     = "PostgreSQL from application tasks"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

resource "aws_db_subnet_group" "this" {
  name       = "${var.name_prefix}-db"
  subnet_ids = aws_subnet.private[*].id
  tags       = var.tags
}

resource "aws_db_instance" "postgres" {
  identifier                  = "${var.name_prefix}-postgres"
  engine                      = "postgres"
  engine_version              = "16"
  instance_class              = var.db_instance_class
  allocated_storage           = var.db_allocated_storage_gb
  storage_encrypted           = true
  multi_az                    = true
  publicly_accessible         = false
  db_subnet_group_name        = aws_db_subnet_group.this.name
  vpc_security_group_ids      = [aws_security_group.db.id]
  username                    = "eaop_owner"
  manage_master_user_password = true
  backup_retention_period     = 7
  deletion_protection         = true
  skip_final_snapshot         = false
  final_snapshot_identifier   = "${var.name_prefix}-final"
  tags                        = var.tags
}

# Containers for the secrets the connectors and webhook endpoints name by environment variable (their VALUES are set outside Terraform).
resource "aws_secretsmanager_secret" "connector_keys" {
  name = "${var.name_prefix}/connector-keys"
  tags = var.tags
}

resource "aws_secretsmanager_secret" "webhook_signing" {
  name = "${var.name_prefix}/webhook-signing"
  tags = var.tags
}
