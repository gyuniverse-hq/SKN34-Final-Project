variable "region" {
  description = "AWS region for every resource."
  type        = string
  default     = "ap-northeast-2"
}

variable "name" {
  description = "Prefix for resource names (cluster, database, cache)."
  type        = string
  default     = "vishue"
}

variable "kubernetes_version" {
  description = "EKS Kubernetes version. Must be one EKS currently supports."
  type        = string
  default     = "1.34"
}

variable "node_instance_types" {
  description = "Instance types for the managed node group (prod and dev namespaces share it)."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_count" {
  description = "Desired node count. Two nodes in two AZs keep one replica per AZ."
  type        = number
  default     = 2
}

variable "db_instance_class" {
  description = "RDS instance class for the production PostgreSQL."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_multi_az" {
  description = "Standby replica in a second AZ. Doubles the database cost; turn on for launch."
  type        = bool
  default     = false
}

variable "db_deletion_protection" {
  description = "Block `terraform destroy` from deleting the production database."
  type        = bool
  default     = true
}

variable "redis_node_type" {
  description = "ElastiCache node type for the production cache."
  type        = string
  default     = "cache.t4g.micro"
}

variable "github_repository" {
  description = "owner/repo allowed to deploy the dev environment through GitHub OIDC."
  type        = string
  default     = "gyuniverse-hq/SKN34-Final-Project"
}
