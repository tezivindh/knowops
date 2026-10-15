mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = { names = ["ap-south-1a", "ap-south-1b"] }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}
run "capstone_infrastructure" {
  command = plan
  variables { admin_cidrs = ["203.0.113.10/32"] }
  assert {
    condition     = length(aws_subnet.public) == 2
    error_message = "The capstone needs two public subnets."
  }
  assert {
    condition     = aws_eks_node_group.main.scaling_config[0].desired_size >= 1
    error_message = "EKS needs at least one worker node."
  }
  assert {
    condition     = aws_eks_cluster.main.access_config[0].authentication_mode == "API"
    error_message = "Use EKS access entries for deployment identity."
  }
}
