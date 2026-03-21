output "project" {
  value = var.project
}

output "region" {
  value = var.region
}

output "master_ip" {
  value = google_compute_instance.aiot_master.network_interface[0].access_config[0].nat_ip
}

output "worker_01_ip" {
  value = google_compute_instance.aiot_worker_01.network_interface[0].access_config[0].nat_ip
}

output "worker_02_ip" {
  value = google_compute_instance.aiot_worker_02.network_interface[0].access_config[0].nat_ip
}
