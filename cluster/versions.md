# Cluster versions
## kubectl/server
Client Version: v1.32.13-gke.100.1+bf9f3133c9dd69
Kustomize Version: v5.5.0
Server Version: v1.32.13

## Nodes
NAME             STATUS   ROLES           AGE     VERSION    INTERNAL-IP     EXTERNAL-IP   OS-IMAGE                  KERNEL-VERSION                    CONTAINER-RUNTIME
aiot-master      Ready    control-plane   5d14h   v1.32.13   10.132.0.2      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
aiot-worker-01   Ready    worker          5d14h   v1.32.13   10.132.0.3      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
aiot-worker-02   Ready    worker          5d14h   v1.32.13   10.132.0.4      <none>        CentOS Stream 9           5.14.0-691.el9.x86_64             containerd://2.2.3
oci-e5-node1     Ready    worker          5d4h    v1.32.13   172.16.200.10   <none>        Oracle Linux Server 9.7   6.12.0-201.74.2.1.el9uek.x86_64   containerd://2.2.3
oci-e5-node2     Ready    worker          5d4h    v1.32.13   172.16.200.11   <none>        Oracle Linux Server 9.7   6.12.0-201.74.2.1.el9uek.x86_64   containerd://2.2.3
oci-test-node1   Ready    ml-training     4d1h    v1.32.13   172.16.200.12   <none>        Oracle Linux Server 9.7   6.12.0-201.74.2.1.el9uek.x86_64   containerd://2.2.3

## API resources
NAME                                SHORTNAMES           APIVERSION                                 NAMESPACED   KIND
componentstatuses                   cs                   v1                                         false        ComponentStatus
namespaces                          ns                   v1                                         false        Namespace
nodes                               no                   v1                                         false        Node
persistentvolumes                   pv                   v1                                         false        PersistentVolume
mutatingwebhookconfigurations                            admissionregistration.k8s.io/v1            false        MutatingWebhookConfiguration
validatingadmissionpolicies                              admissionregistration.k8s.io/v1            false        ValidatingAdmissionPolicy
validatingadmissionpolicybindings                        admissionregistration.k8s.io/v1            false        ValidatingAdmissionPolicyBinding
validatingwebhookconfigurations                          admissionregistration.k8s.io/v1            false        ValidatingWebhookConfiguration
customresourcedefinitions           crd,crds             apiextensions.k8s.io/v1                    false        CustomResourceDefinition
apiservices                                              apiregistration.k8s.io/v1                  false        APIService
clusterworkflowtemplates            clusterwftmpl,cwft   argoproj.io/v1alpha1                       false        ClusterWorkflowTemplate
clusterissuers                                           cert-manager.io/v1                         false        ClusterIssuer
certificatesigningrequests          csr                  certificates.k8s.io/v1                     false        CertificateSigningRequest
flowschemas                                              flowcontrol.apiserver.k8s.io/v1            false        FlowSchema
prioritylevelconfigurations                              flowcontrol.apiserver.k8s.io/v1            false        PriorityLevelConfiguration
profiles                                                 kubeflow.org/v1                            false        Profile
clusters                                                 management.cattle.io/v3                    false        Cluster
globalrolebindings                                       management.cattle.io/v3                    false        GlobalRoleBinding
globalroles                                              management.cattle.io/v3                    false        GlobalRole
kontainerdrivers                                         management.cattle.io/v3                    false        KontainerDriver
nodedrivers                                              management.cattle.io/v3                    false        NodeDriver
roletemplates                                            management.cattle.io/v3                    false        RoleTemplate
users                                                    management.cattle.io/v3                    false        User
compositecontrollers                cc,cctl              metacontroller.k8s.io/v1alpha1             false        CompositeController
decoratorcontrollers                dec,decorators       metacontroller.k8s.io/v1alpha1             false        DecoratorController
nodes                                                    metrics.k8s.io/v1beta1                     false        NodeMetrics
clusterdomainclaims                 cdc                  networking.internal.knative.dev/v1alpha1   false        ClusterDomainClaim
ingressclasses                                           networking.k8s.io/v1                       false        IngressClass
runtimeclasses                                           node.k8s.io/v1                             false        RuntimeClass
clusterimagecatalogs                                     postgresql.cnpg.io/v1                      false        ClusterImageCatalog
clusterrolebindings                                      rbac.authorization.k8s.io/v1               false        ClusterRoleBinding
clusterroles                                             rbac.authorization.k8s.io/v1               false        ClusterRole
priorityclasses                     pc                   scheduling.k8s.io/v1                       false        PriorityClass
clusterservingruntimes                                   serving.kserve.io/v1alpha1                 false        ClusterServingRuntime
clusterstoragecontainers                                 serving.kserve.io/v1alpha1                 false        ClusterStorageContainer
csidrivers                                               storage.k8s.io/v1                          false        CSIDriver
csinodes                                                 storage.k8s.io/v1                          false        CSINode
storageclasses                      sc                   storage.k8s.io/v1                          false        StorageClass
volumeattachments                                        storage.k8s.io/v1                          false        VolumeAttachment
clusterpolicyreports                cpolr                wgpolicyk8s.io/v1alpha2                    false        ClusterPolicyReport
