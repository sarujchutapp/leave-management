data "aws_caller_identity" "current" {}

data "aws_region" "current" {}

locals {
  ssm_bot_token_param      = "${var.ssm_parameter_prefix}/slack-bot-token"
  ssm_signing_secret_param = "${var.ssm_parameter_prefix}/slack-signing-secret"
  ssm_google_sa_param      = "${var.ssm_parameter_prefix}/google-service-account"
}

# --- Artifact -----------------------------------------------------------------
# build.sh (run in WSL) populates ./build with Linux/x86_64 wheels + the app
# code; archive_file zips it and feeds source_code_hash so apply redeploys on
# a code change. The Google service-account.json is NOT bundled — it comes from
# SSM at runtime.
data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/build"
  output_path = "${path.module}/leave-bot.zip"
}

# --- DynamoDB (adopted via `terraform import`, not recreated) ------------------
# Schemas mirror leave/seed.py:create_tables so import shows no diff. The live
# data was provisioned in #15; these blocks let one tool own prod infra.
resource "aws_dynamodb_table" "employees" {
  name         = var.employees_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "slack_user_id"

  attribute {
    name = "slack_user_id"
    type = "S"
  }
}

resource "aws_dynamodb_table" "requests" {
  name         = var.requests_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "request_id"

  attribute {
    name = "request_id"
    type = "S"
  }

  attribute {
    name = "employee_id"
    type = "S"
  }

  attribute {
    name = "start_date"
    type = "S"
  }

  global_secondary_index {
    name            = var.by_employee_index
    hash_key        = "employee_id"
    range_key       = "start_date"
    projection_type = "ALL"
  }
}

# NOTE: the `holidays` table is deferred — creating it needs dynamodb:CreateTable on
# leave_holidays, which the deploy role doesn't have (an admin must widen it, see
# terraform/operator-policy.json). Until then the app degrades to "no holidays"
# (leave/holidays.py catches the missing table/permission). To enable holidays later:
# (1) admin adds the leave_holidays ARN to the deploy role's policy,
# (2) restore this aws_dynamodb_table.holidays block + the HolidaysRead IAM statement,
# (3) terraform apply, then run import_holidays.py.

# --- IAM (least privilege) -----------------------------------------------------
data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
}

resource "aws_iam_role_policy_attachment" "basic_execution" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "lambda" {
  # UpdateItem: the lazy vacation carry_in write (one map attribute per employee
  # per year). GetItem covers employee + the reserved central-policy item.
  statement {
    sid       = "EmployeesReadWrite"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.employees.arn]
  }

  # No DeleteItem — cancelling a request is an UpdateItem, never a delete.
  statement {
    sid = "RequestsReadWrite"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.requests.arn,
      "${aws_dynamodb_table.requests.arn}/index/${var.by_employee_index}",
    ]
  }

  # HolidaysRead is deferred with the holidays table (see note above the IAM section).

  statement {
    sid       = "ReadSecrets"
    actions   = ["ssm:GetParameter*"]
    resources = ["arn:aws:ssm:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:parameter${var.ssm_parameter_prefix}/*"]
  }

  # Decrypt only via SSM — the SecureStrings use the AWS-managed aws/ssm key.
  statement {
    sid       = "DecryptViaSsm"
    actions   = ["kms:Decrypt"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["ssm.${data.aws_region.current.name}.amazonaws.com"]
    }
  }

  # Bolt's lazy listeners re-invoke this same function to do the slow post-ack work.
  statement {
    sid       = "SelfInvoke"
    actions   = ["lambda:InvokeFunction"]
    resources = ["arn:aws:lambda:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:function:${var.function_name}"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.function_name}-policy"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}

# --- Logs ----------------------------------------------------------------------
resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.function_name}"
  retention_in_days = var.log_retention_days
}

# --- Lambda + Function URL -----------------------------------------------------
# AWS_REGION is a reserved Lambda env var (the runtime sets it automatically and
# rejects it as a custom var), so it is intentionally absent here — leave/db.py
# and leave/calendar_client.py read the runtime-provided value.
resource "aws_lambda_function" "leave_bot" {
  function_name = var.function_name
  role          = aws_iam_role.lambda.arn
  runtime       = "python3.12"
  handler       = "lambda_handler.handler"
  architectures = ["x86_64"]
  # 1024 MB — memory scales CPU proportionally, so cold-start imports build faster and
  # the synchronous /dayoff modal-open path acks within Slack's 3s window. At 512 MB the
  # modal opened but the ack still landed just over 3s on cold starts. Still ~$0 here.
  memory_size = 1024
  timeout     = 30

  filename         = data.archive_file.lambda.output_path
  source_code_hash = data.archive_file.lambda.output_base64sha256

  environment {
    variables = {
      EMPLOYEES_TABLE              = var.employees_table
      REQUESTS_TABLE               = var.requests_table
      HOLIDAYS_TABLE               = var.holidays_table
      LEAVE_BOARD_CHANNEL          = var.leave_board_channel
      LEAVE_SHEET_ID               = var.leave_sheet_id
      SLACK_ADMIN_IDS              = var.slack_admin_ids
      TEAM_CALENDAR_ID             = var.team_calendar_id
      GOOGLE_SERVICE_ACCOUNT_FILE  = "/tmp/service-account.json"
      SLACK_BOT_TOKEN_PARAM        = local.ssm_bot_token_param
      SLACK_SIGNING_SECRET_PARAM   = local.ssm_signing_secret_param
      GOOGLE_SERVICE_ACCOUNT_PARAM = local.ssm_google_sa_param
    }
  }

  depends_on = [
    aws_iam_role_policy_attachment.basic_execution,
    aws_cloudwatch_log_group.lambda,
  ]
}

resource "aws_lambda_function_url" "leave_bot" {
  function_name      = aws_lambda_function.leave_bot.function_name
  authorization_type = "NONE"
}

# Function URLs with auth type NONE still need an explicit public invoke grant;
# Slack's request signature (verified in-process) is the real authenticator.
resource "aws_lambda_permission" "function_url" {
  statement_id           = "AllowPublicFunctionUrlInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.leave_bot.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

# An auth-type-NONE Function URL also needs lambda:InvokeFunction granted to the
# public principal (per the AWS console's own guidance); with only InvokeFunctionUrl
# the URL returns 403 AccessDeniedException before the function runs. The
# FunctionUrlAuthType condition is only valid on InvokeFunctionUrl, so this grant
# is unconditioned — abuse is bounded by the in-process Slack signature check, which
# rejects any request (direct invoke included) that isn't a validly signed Slack call.
resource "aws_lambda_permission" "function_invoke" {
  statement_id  = "AllowPublicFunctionInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.leave_bot.function_name
  principal     = "*"
}

# --- Secrets (declared as code; real values set out-of-band in #17) ------------
resource "aws_ssm_parameter" "slack_bot_token" {
  name  = local.ssm_bot_token_param
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "slack_signing_secret" {
  name  = local.ssm_signing_secret_param
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}

resource "aws_ssm_parameter" "google_service_account" {
  name  = local.ssm_google_sa_param
  type  = "SecureString"
  value = "placeholder"

  lifecycle {
    ignore_changes = [value]
  }
}
