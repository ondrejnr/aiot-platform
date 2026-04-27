.PHONY: help prereqs init cilium platform helm apply restore all status

help:
	@echo "aiot-platform — install targets (run from repo root)"
	@echo ""
	@echo "  make prereqs   # 00 — containerd/kubeadm/helm on this VM"
	@echo "  make init      # 01 — kubeadm init (master only)"
	@echo "  make cilium    # 02 — Cilium CNI"
	@echo "  make platform  # 03 — cert-manager + ingress + storage"
	@echo "  make helm      # 04 — all helm releases"
	@echo "  make apply     # 05 — CRDs + manifests"
	@echo "  make restore   # 06 — Velero restore from R2 (needs env vars)"
	@echo "  make all       # 02..05 in sequence"
	@echo "  make status    # cluster overview"

prereqs:
	sudo bash install/00-vm-prereqs.sh
init:
	sudo bash install/01-init-master.sh
cilium:
	sudo bash install/02-cilium.sh
platform:
	sudo bash install/03-platform.sh
helm:
	sudo bash install/04-helm-charts.sh
apply:
	sudo bash install/05-apply-cluster.sh
restore:
	@echo Use: ./install/06-k8up-restore.sh list \<ns\> or ./install/06-k8up-restore.sh restore \<ns\> \<pvc\>
all: cilium platform helm apply

status:
	kubectl get nodes -o wide
	@echo
	helm list -A
	@echo
	kubectl get pods -A | grep -vE 'Running|Completed' || echo "All pods healthy"
