resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/magicbooking-calendar-sync"
  retention_in_days = 14
}

resource "aws_sns_topic" "alerts" {
  name = "magicbooking-calendar-sync-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "magicbooking-calendar-sync-errors"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 1
  metric_name         = "Errors"
  namespace           = "AWS/Lambda"
  period              = 86400
  statistic           = "Sum"
  threshold           = 1
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.sync.function_name
  }

  alarm_actions = [aws_sns_topic.alerts.arn]
}
