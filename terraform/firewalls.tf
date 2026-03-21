resource "google_compute_firewall" "aiot_cloudbeaver" {
  name          = "aiot-cloudbeaver"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["aiot"]

  allow {
    protocol = "tcp"
    ports    = ["31978"]
  }
}

resource "google_compute_firewall" "allow_all_k8s_internal" {
  name          = "allow-all-k8s-internal"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 100
  description   = "Allow all traffic between K8s nodes - test env"
  source_ranges = ["10.132.0.0/20"]

  allow {
    protocol = "all"
  }
}

resource "google_compute_firewall" "allow_signoz_nodeport" {
  name          = "allow-signoz-nodeport"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["30255"]
  }
}

resource "google_compute_firewall" "default_allow_icmp" {
  name          = "default-allow-icmp"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 65534
  description   = "Allow ICMP from anywhere"
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "icmp"
  }
}

resource "google_compute_firewall" "default_allow_internal" {
  name          = "default-allow-internal"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 65534
  description   = "Allow internal traffic on the default network"
  source_ranges = ["10.128.0.0/9"]

  allow {
    protocol = "tcp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "udp"
    ports    = ["0-65535"]
  }

  allow {
    protocol = "icmp"
  }
}

resource "google_compute_firewall" "default_allow_rdp" {
  name          = "default-allow-rdp"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 65534
  description   = "Allow RDP from anywhere"
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["3389"]
  }
}

resource "google_compute_firewall" "default_allow_ssh" {
  name          = "default-allow-ssh"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 65534
  description   = "Allow SSH from anywhere"
  source_ranges = ["0.0.0.0/0"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "k8s_external" {
  name          = "k8s-external"
  project       = var.project
  network       = google_compute_network.default.self_link
  direction     = "INGRESS"
  priority      = 1000
  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["k8s-master", "k8s-worker"]

  allow {
    protocol = "tcp"
    ports    = ["30000-32767"]
  }

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  allow {
    protocol = "tcp"
    ports    = ["6443"]
  }

  allow {
    protocol = "tcp"
    ports    = ["80"]
  }
}

resource "google_compute_firewall" "k8s_internal" {
  name        = "k8s-internal"
  project     = var.project
  network     = google_compute_network.default.self_link
  direction   = "INGRESS"
  priority    = 1000
  source_tags = ["k8s-master", "k8s-worker"]
  target_tags = ["k8s-master", "k8s-worker"]

  allow {
    protocol = "icmp"
  }

  allow {
    protocol = "tcp"
  }

  allow {
    protocol = "udp"
  }
}
