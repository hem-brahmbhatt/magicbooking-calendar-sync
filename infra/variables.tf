variable "aws_region" {
  type    = string
  default = "eu-west-2"
}

variable "alert_email" {
  description = "Email address to receive sync-failure alerts. Pass with -var or a gitignored terraform.tfvars — never hardcode."
  type        = string
}

variable "schedule_expression" {
  description = "EventBridge Scheduler cron expression for the daily sync."
  type        = string
  default     = "cron(0 3 * * ? *)"
}
