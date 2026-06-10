variable "aws_region" {
  type        = string
  description = "AWS region for all resources."
}

variable "function_name" {
  type        = string
  description = "Lambda function name (also used to derive the role, policy, and log group names)."
  default     = "leave-bot"
}

variable "team_calendar_id" {
  type        = string
  description = "Google Calendar ID of the shared team leave calendar."
}

variable "employees_table" {
  type        = string
  description = "DynamoDB employees table name. Adopted via terraform import (not recreated)."
  default     = "leave_employees"
}

variable "requests_table" {
  type        = string
  description = "DynamoDB requests table name. Adopted via terraform import (not recreated)."
  default     = "leave_requests"
}

variable "by_employee_index" {
  type        = string
  description = "Name of the requests-table GSI partitioned by employee_id."
  default     = "by_employee"
}

variable "ssm_parameter_prefix" {
  type        = string
  description = "Path prefix for the three SSM SecureString parameters holding the secrets."
  default     = "/leave-bot"
}

variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention for the Lambda."
  default     = 14
}
