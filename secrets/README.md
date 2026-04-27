# Encrypted Secrets

This directory holds **sops + age** encrypted Secret manifests. ArgoCD's
`argocd-repo-server` mounts the private age key (created during
`bootstrap/04-sops-age.sh`) and the KSOPS plugin decrypts at sync time.

## Generate a new key

```bash
age-keygen -o age.key
# Public:  copy "age1xxxxx..." into secrets/.sops.yaml `age:` field
# Private: NEVER commit; pass to bootstrap/04-sops-age.sh as AGE_KEY_FILE
```

## Encrypt

```bash
sops --encrypt --in-place secrets/<ns>/<name>.yaml
```

## Required secrets for fresh install

| File                                | Used by               |
|-------------------------------------|-----------------------|
| secrets/k8up-system/r2-creds.yaml   | k8up restic backups   |
| secrets/k8up-system/k8up-repo.yaml  | restic password       |
| secrets/etcd-backup/r2-credentials.yaml | etcd snapshot CronJob |
| secrets/aiot/groq-api-key.yaml      | Groq LLM proxy        |
| secrets/k8sgpt/llm-keys.yaml        | k8sgpt providers      |
| secrets/jenkins/admin.yaml          | Jenkins admin user    |
| secrets/gitea/admin.yaml            | Gitea admin user      |
| secrets/cattle-system/bootstrap.yaml | Rancher initial pwd  |
