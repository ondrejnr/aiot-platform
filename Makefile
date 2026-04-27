.PHONY: help prereqs init cni platform helm apply restore all status

help:
	@echo "aiot-platform — install targets (run from repo root)"
	@echo ""
	@echo "  make prereqs   # 00 — containerd/kubeadm/helm on this VM"
	@echo "  make init      # 01 — kubeadm init (master only)"
	@echo "  make cni       # 02 — Flannel CNI"
	@echo "  make platform  # 03 — cert-manager + ingress + storage"
	@echo "  make helm      # 04 — all helm releases"
	@echo "  make apply     # 05 — CRDs + manifests"
	@echo "  make restore   # 06 — Velero restore from R2 (needs env vars)"
	@echo "  make all       # 02..05 in sequence"
	@echo "  make status    # cluster overview"

prereqs:
	sudo bash bootstrap/00-vm-prereqs.sh
init:
	sudo bash bootstrap/01-kubeadm-init.sh
cni:
	sudo bash bootstrap/02-flannel.sh
platform:
	sudo bash bootstrap/03-sealed-secrets.sh
helm:
	sudo bash install/04-helm-charts.sh
apply:
	sudo bash install/05-apply-cluster.sh
restore:
	@echo Use: ./install/06-k8up-restore.sh list \<ns\> or ./install/06-k8up-restore.sh restore \<ns\> \<pvc\>
all: cni platform helm apply

status:
	kubectl get nodes -o wide
	@echo
	helm list -A
	@echo
	kubectl get pods -A | grep -vE 'Running|Completed' || echo "All pods healthy"
