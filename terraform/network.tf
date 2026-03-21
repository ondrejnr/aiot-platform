resource "google_compute_network" "default" {
  name                            = "default"
  project                         = var.project
  auto_create_subnetworks         = true
  description                     = "Default network for the project"
  routing_mode                    = "REGIONAL"
  delete_default_routes_on_create = false
}
