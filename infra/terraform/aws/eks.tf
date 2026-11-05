module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.0"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  vpc_id     = module.vpc.vpc_id
  subnet_ids = module.vpc.private_subnets

  # kubectl from laptops and GitHub Actions; access itself is controlled by access entries.
  endpoint_public_access                   = true
  enable_cluster_creator_admin_permissions = true

  addons = {
    coredns    = {}
    kube-proxy = {}
    vpc-cni = {
      before_compute = true
    }
    eks-pod-identity-agent = {
      before_compute = true
    }
    aws-ebs-csi-driver = {}
  }

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.node_instance_types
      min_size       = 2
      max_size       = 4
      desired_size   = var.node_count
    }
  }
}

# EBS volumes for PersistentVolumeClaims (e.g. a Neo4j StatefulSet if AuraDB is replaced).
module "ebs_csi_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                      = "${var.name}-ebs-csi"
  attach_aws_ebs_csi_policy = true

  associations = {
    ebs_csi = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = "ebs-csi-controller-sa"
    }
  }
}

# External Secrets Operator reads only vishue/* from Secrets Manager.
module "external_secrets_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.0"

  name                 = "${var.name}-external-secrets"
  attach_custom_policy = true
  policy_statements = [
    {
      sid       = "ReadVishueSecrets"
      actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      resources = ["arn:aws:secretsmanager:${var.region}:${data.aws_caller_identity.current.account_id}:secret:vishue/*"]
    }
  ]

  associations = {
    external_secrets = {
      cluster_name    = module.eks.cluster_name
      namespace       = "external-secrets"
      service_account = "external-secrets"
    }
  }
}

data "aws_caller_identity" "current" {}
