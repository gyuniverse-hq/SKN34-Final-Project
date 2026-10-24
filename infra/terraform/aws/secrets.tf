# Secrets Manager entries read by External Secrets (one per service and environment).
# Terraform writes the first version only: connection strings it knows plus empty API keys.
# Fill the keys in the console afterwards; later edits are kept (ignore_changes).

locals {
  initial_secrets = {
    "production/api" = {
      DATABASE_URL        = local.database_url
      REDIS_URL           = "rediss://${local.redis_host}:6379/0"
      NAVER_CLIENT_ID     = ""
      NAVER_CLIENT_SECRET = ""
      YOUTUBE_API_KEY     = ""
    }
    "production/chatbot" = {
      REDIS_URL      = "rediss://${local.redis_host}:6379/1"
      NEO4J_PASSWORD = ""
      LLM_API_KEY    = ""
    }
    # Dev: PostgreSQL is the shared Supabase database (session pooler URL with ?ssl=require);
    # Redis and Neo4j run in the vishue-dev namespace and are wired by the Helm chart.
    "dev/api" = {
      DATABASE_URL        = ""
      NAVER_CLIENT_ID     = ""
      NAVER_CLIENT_SECRET = ""
      YOUTUBE_API_KEY     = ""
    }
    "dev/chatbot" = {
      LLM_API_KEY = ""
    }
  }
}

resource "aws_secretsmanager_secret" "app" {
  for_each = local.initial_secrets

  name                    = "vishue/${each.key}"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "app" {
  for_each = local.initial_secrets

  secret_id     = aws_secretsmanager_secret.app[each.key].id
  secret_string = jsonencode(each.value)

  lifecycle {
    ignore_changes = [secret_string]
  }
}
