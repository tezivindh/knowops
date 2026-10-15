variable "aws_region" {
  type    = string
  default = "ap-south-1"
}
variable "project_name" {
  type    = string
  default = "knowops"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,24}$", var.project_name))
    error_message = "Use a lowercase project name of 3–25 characters."
  }
}
variable "kubernetes_version" {
  type    = string
  default = "1.34"
}
variable "admin_cidrs" {
  description = "Public IPv4 CIDRs allowed to reach the EKS API, including the deployment runner."
  type        = list(string)
  validation {
    condition     = length(var.admin_cidrs) > 0 && alltrue([for cidr in var.admin_cidrs : can(cidrnetmask(cidr)) && cidr != "0.0.0.0/0"])
    error_message = "Supply explicit IPv4 CIDRs; 0.0.0.0/0 is not allowed."
  }
}
variable "node_instance_types" {
  type    = list(string)
  default = ["t3.large"]
}
variable "node_desired_size" {
  type    = number
  default = 2
  validation {
    condition     = var.node_desired_size >= 1 && var.node_desired_size <= 3
    error_message = "Choose between 1 and 3 worker nodes."
  }
}
variable "github_repository" {
  description = "Repository allowed to deploy through GitHub OIDC."
  type        = string
  default     = "tezivindh/knowops"
}
variable "create_github_oidc_provider" {
  description = "Set false if this AWS account already has the GitHub OIDC provider."
  type        = bool
  default     = true
}
