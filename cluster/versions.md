# Cluster versions

## Kubernetes
clientVersion:
  buildDate: "2026-03-24T06:35:26Z"
  compiler: gc
  gitCommit: bf9f3133c9dd69746611729d08bb4a01bb90048c
  gitTreeState: clean
  gitVersion: v1.32.13-gke.100.1+bf9f3133c9dd69
  goVersion: go1.24.13
  major: "1"
  minor: 32+
  platform: linux/amd64
kustomizeVersion: v5.5.0
serverVersion:
  buildDate: "2026-02-26T20:20:24Z"
  compiler: gc
  gitCommit: 6172d7357c6287643350a4fc7e048f24098f2a1b
  gitTreeState: clean
  gitVersion: v1.32.13
  goVersion: go1.24.13
  major: "1"
  minor: "32"

## Cilium
version: 1.16.6
chart: cilium-1.16.6
revision: 2
updated: 2026-04-27 04:08:22.154319931 +0000 UTC

## All Helm releases
NAME                  	NAMESPACE                    	REVISION	UPDATED                                	STATUS  	CHART                           	APP VERSION
argocd                	argocd                       	1       	2026-04-26 08:49:12.050585428 +0000 UTC	deployed	argo-cd-7.7.10                  	v2.13.2    
cilium                	kube-system                  	2       	2026-04-27 04:08:22.154319931 +0000 UTC	deployed	cilium-1.16.6                   	1.16.6     
fleet                 	cattle-fleet-system          	2       	2026-04-19 20:54:30.563836328 +0000 UTC	deployed	fleet-108.0.3+up0.14.3          	0.14.3     
fleet-crd             	cattle-fleet-system          	1       	2026-04-19 20:51:13.869196002 +0000 UTC	deployed	fleet-crd-108.0.3+up0.14.3      	0.14.3     
jenkins               	jenkins                      	4       	2026-04-21 01:38:35.796302023 +0000 UTC	deployed	jenkins-5.9.18                  	2.555.1    
k8s-infra             	signoz                       	1       	2026-04-14 02:30:53.865931631 +0000 UTC	deployed	k8s-infra-0.15.0                	0.139.0    
k8sgpt-operator       	k8sgpt                       	1       	2026-04-14 04:55:25.595000331 +0000 UTC	deployed	k8sgpt-operator-0.2.27          	0.2.25     
k8up                  	k8up-system                  	1       	2026-04-22 05:59:57.789155486 +0000 UTC	deployed	k8up-4.9.0                      	           
opentelemetry-operator	opentelemetry-operator-system	1       	2026-04-15 20:01:36.297975665 +0000 UTC	deployed	opentelemetry-operator-0.109.2  	0.148.0    
prometheus            	monitoring                   	2       	2026-04-19 22:01:21.018332006 +0000 UTC	deployed	kube-prometheus-stack-83.4.1    	v0.90.1    
rancher               	cattle-system                	1       	2026-04-19 20:41:20.21754893 +0000 UTC 	deployed	rancher-2.13.3                  	v2.13.3    
rancher-turtles       	cattle-turtles-system        	1       	2026-04-19 20:51:57.763524109 +0000 UTC	deployed	rancher-turtles-108.0.4+up0.25.4	0.25.4     
rancher-webhook       	cattle-system                	2       	2026-04-19 20:51:50.740988151 +0000 UTC	deployed	rancher-webhook-108.0.3+up0.9.3 	0.9.3      
signoz                	signoz                       	3       	2026-04-19 22:00:14.829358923 +0000 UTC	deployed	signoz-0.117.1                  	v0.117.1   

## Nodes
NAME             STATUS   ROLES           AGE     VERSION    INTERNAL-IP     EXTERNAL-IP   OS-IMAGE                  KERNEL-VERSION                    CONTAINER-RUNTIME
aiot-master      Ready    control-plane   13d     v1.32.13   10.132.0.2      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
aiot-worker-01   Ready    worker          4d13h   v1.32.13   10.132.0.3      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
aiot-worker-02   Ready    worker          4d15h   v1.32.13   10.132.0.4      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
oci-e5-node1     Ready    worker          12d     v1.32.13   172.16.200.10   <none>        Oracle Linux Server 9.7   6.12.0-201.74.2.1.el9uek.x86_64   containerd://2.2.3
oci-e5-node2     Ready    worker          12d     v1.32.13   172.16.200.11   <none>        Oracle Linux Server 9.7   6.12.0-201.74.2.1.el9uek.x86_64   containerd://2.2.3
