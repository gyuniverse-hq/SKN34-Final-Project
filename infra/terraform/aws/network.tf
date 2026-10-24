data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, 2)
}

# Two AZs. Nodes, databases and caches live in private subnets; only load balancers are public.
# One NAT gateway keeps the cost down (outbound traffic: Naver, YouTube, LLM, image pulls).
module "vpc" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "~> 6.0"

  name = var.name
  cidr = "10.40.0.0/16"
  azs  = local.azs

  public_subnets      = ["10.40.0.0/24", "10.40.1.0/24"]
  private_subnets     = ["10.40.10.0/24", "10.40.11.0/24"]
  database_subnets    = ["10.40.20.0/24", "10.40.21.0/24"]
  elasticache_subnets = ["10.40.30.0/24", "10.40.31.0/24"]

  create_database_subnet_group    = true
  create_elasticache_subnet_group = true

  enable_nat_gateway = true
  single_nat_gateway = true

  public_subnet_tags  = { "kubernetes.io/role/elb" = "1" }
  private_subnet_tags = { "kubernetes.io/role/internal-elb" = "1" }
}
