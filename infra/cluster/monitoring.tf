# CloudWatch watches the node from outside: it still reports when the node is too broken
# for Prometheus, which runs on it, to say anything. Prometheus and Grafana watch the app
# from inside (k8s/monitoring). All of this is in the CloudWatch free tier: basic EC2
# metrics, three alarms and one dashboard.

# Optional email for the alarms (alert_email in terraform.tfvars). AWS first sends a
# confirmation message: the alarms reach the address only once it is confirmed
resource "aws_sns_topic" "alarms" {
  count = var.alert_email == "" ? 0 : 1
  name  = "devops-lab-alarms"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alarms[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

locals {
  notify = aws_sns_topic.alarms[*].arn
}

# The hardware or the network under the node fails: AWS moves the instance to healthy
# hardware, with the same ID, IP addresses and disk
resource "aws_cloudwatch_metric_alarm" "system_check" {
  alarm_name          = "devops-lab-node-system-check"
  alarm_description   = "The system status check fails: recover the instance on other hardware"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  dimensions          = { InstanceId = aws_instance.k3s.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = concat(["arn:aws:automate:${var.region}:ec2:recover"], local.notify)
}

# The operating system stops answering (kernel stuck, memory exhausted): reboot it
resource "aws_cloudwatch_metric_alarm" "instance_check" {
  alarm_name          = "devops-lab-node-instance-check"
  alarm_description   = "The instance status check fails: the operating system does not answer"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_Instance"
  dimensions          = { InstanceId = aws_instance.k3s.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  alarm_actions       = concat(["arn:aws:automate:${var.region}:ec2:reboot"], local.notify)
}

# The CPU is saturated for 15 minutes. On this node that is mostly the LLM, which runs on
# the CPU: the signal that the model needs a GPU or a managed service
resource "aws_cloudwatch_metric_alarm" "cpu" {
  alarm_name          = "devops-lab-node-cpu"
  alarm_description   = "CPU above 90% for 15 minutes"
  namespace           = "AWS/EC2"
  metric_name         = "CPUUtilization"
  dimensions          = { InstanceId = aws_instance.k3s.id }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 3
  threshold           = 90
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = local.notify
  ok_actions          = local.notify
}

resource "aws_cloudwatch_dashboard" "node" {
  dashboard_name = "devops-lab"

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "CPU %", region = var.region, stat = "Average", period = 300
          metrics = [["AWS/EC2", "CPUUtilization", "InstanceId", aws_instance.k3s.id]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title = "Network bytes", region = var.region, stat = "Sum", period = 300
          metrics = [
            ["AWS/EC2", "NetworkIn", "InstanceId", aws_instance.k3s.id],
            ["AWS/EC2", "NetworkOut", "InstanceId", aws_instance.k3s.id],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title = "Status checks failed", region = var.region, stat = "Maximum", period = 60
          metrics = [
            ["AWS/EC2", "StatusCheckFailed_System", "InstanceId", aws_instance.k3s.id],
            ["AWS/EC2", "StatusCheckFailed_Instance", "InstanceId", aws_instance.k3s.id],
          ]
        }
      },
      {
        type = "alarm", x = 12, y = 6, width = 12, height = 6
        properties = {
          title = "Alarms"
          alarms = [
            aws_cloudwatch_metric_alarm.system_check.arn,
            aws_cloudwatch_metric_alarm.instance_check.arn,
            aws_cloudwatch_metric_alarm.cpu.arn,
          ]
        }
      },
    ]
  })
}
