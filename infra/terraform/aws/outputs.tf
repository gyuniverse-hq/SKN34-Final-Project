output "cluster_name" {
  description = "GitHub repository variable EKS_CLUSTER_NAME."
  value       = module.eks.cluster_name
}

output "region" {
  description = "GitHub repository variable AWS_REGION."
  value       = var.region
}

output "github_dev_deploy_role_arn" {
  description = "GitHub repository variable AWS_DEV_DEPLOY_ROLE_ARN (enables the dev deploy job)."
  value       = aws_iam_role.github_dev_deploy.arn
}

output "configure_kubectl" {
  description = "Run once on your machine to use kubectl/helm against the cluster."
  value       = "aws eks update-kubeconfig --name ${module.eks.cluster_name} --region ${var.region}"
}

output "postgres_endpoint" {
  description = "Production RDS endpoint (the full URL is in Secrets Manager vishue/production/api)."
  value       = aws_db_instance.main.address
}

output "redis_endpoint" {
  description = "Production ElastiCache primary endpoint (TLS)."
  value       = local.redis_host
}

output "secret_names" {
  description = "Secrets Manager entries to fill with API keys."
  value       = [for s in aws_secretsmanager_secret.app : s.name]
}
