# GitHub Actions deploys the dev environment with short-lived credentials (no stored AWS keys).
# Only the develop branch of this repository can assume the role.

resource "aws_iam_openid_connect_provider" "github" {
  url            = "https://token.actions.githubusercontent.com"
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_policy_document" "github_dev_deploy_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.github.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:ref:refs/heads/develop"]
    }
  }
}

resource "aws_iam_role" "github_dev_deploy" {
  name               = "${var.name}-github-dev-deploy"
  assume_role_policy = data.aws_iam_policy_document.github_dev_deploy_trust.json
}

# Enough for `aws eks update-kubeconfig`; Kubernetes permissions come from the access entry.
resource "aws_iam_role_policy" "github_dev_deploy" {
  name = "describe-cluster"
  role = aws_iam_role.github_dev_deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["eks:DescribeCluster"]
      Resource = module.eks.cluster_arn
    }]
  })
}
