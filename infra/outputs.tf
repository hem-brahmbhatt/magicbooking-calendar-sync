output "lambda_function_name" {
  value = aws_lambda_function.sync.function_name
}

output "ssm_parameter_names" {
  value = [for p in aws_ssm_parameter.secrets : p.name]
}
