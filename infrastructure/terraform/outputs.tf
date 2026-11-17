output "vpc_id" {
  description = "Identifier of the VPC."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "Private subnets for the tasks and the database."
  value       = aws_subnet.private[*].id
}

output "database_endpoint" {
  description = "PostgreSQL endpoint (private)."
  value       = aws_db_instance.postgres.address
}

output "app_security_group_id" {
  description = "Security group to attach to the API and worker tasks."
  value       = aws_security_group.app.id
}
