# AIOT Platform Documentation

This directory contains operational and deployment guides for the AIOT platform.

## Guides

### [AUTHENTIK-SETUP.md](./AUTHENTIK-SETUP.md)

Complete Authentik OIDC and SAML configuration guide for the hetzner-new cluster.

**Covers:**
- Authentik server deployment and configuration
- OAuth2-Proxy setup for forward-auth
- Application integrations:
  - Headlamp (Kubernetes Dashboard with OIDC + RBAC)
  - Jenkins (CI/CD with native OIDC)
  - Gitea (Git repository with OAuth2)
  - Chef Automate (Infrastructure automation with SAML)
- Known issues and fixes:
  - NGINX buffer overflow causing login loops
  - Certificate validation failures
  - oauth2-proxy redirect loops
  - SAML 405 errors
- Deployment checklist for new clusters
- Troubleshooting guide with debug commands
- Testing scripts and references

**Read this when:**
- Deploying a new cluster from scratch
- Debugging authentication/SSO issues
- Setting up a new application with Authentik
- Rebuilding the cluster (important notes about certificate rotation)

---

## Directory Structure

```
docs/
├── README.md (this file)
└── AUTHENTIK-SETUP.md
```

## Quick Links

- **Main Repository:** `/root/aiot-platform` (hetzner-new) or `github.com/ondrejnr/aiot-platform`
- **Authentik Instance:** `https://authentik.46.4.123.8.nip.io/`
- **INSTALL.md:** See main repository root for initial deployment steps

---

## Version Info

**Last Updated:** June 2, 2026  
**Authentik Version:** 2026.5.2  
**Cluster:** hetzner-new (k3d/k3s v1.31.5)  
**Domain:** `*.46.4.123.8.nip.io`  
**Flux Version:** v2.6.4
