output "function_url" {
  description = "Lambda Function URL — set as the Slack app's Request URL and Interactivity Request URL."
  value       = aws_lambda_function_url.leave_bot.function_url
}
