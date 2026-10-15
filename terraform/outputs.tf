output "vpc_id" { value = aws_vpc.main.id }
output "public_subnet_ids" { value = aws_subnet.public[*].id }
output "cluster_name" { value = aws_eks_cluster.main.name }
output "region" { value = var.aws_region }
output "github_deploy_role_arn" { value = aws_iam_role.github_deploy.arn }
output "configure_kubectl" {
  value = "aws eks update-kubeconfig --region ${var.aws_region} --name ${aws_eks_cluster.main.name}"
}
