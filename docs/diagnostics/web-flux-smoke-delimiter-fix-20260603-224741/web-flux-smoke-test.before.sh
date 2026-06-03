#!/usr/bin/env bash
set +e

OUT_DIR="${1:-/tmp/web-flux-smoke-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT_DIR"

echo "OUT_DIR=$OUT_DIR"

flux get kustomizations -A > "$OUT_DIR/flux-kustomizations.txt" 2>&1 || true
flux get helmreleases -A > "$OUT_DIR/flux-helmreleases.txt" 2>&1 || true
kubectl get ingress -A -o yaml > "$OUT_DIR/ingress-all.yaml" 2>/dev/null || true
kubectl get ingress -A -o wide > "$OUT_DIR/ingress-wide.txt" 2>&1 || true

cat > "$OUT_DIR/known-hosts.tsv" <<'HOSTS'
qdrant.46.4.123.8.nip.io    /collections    JSON_OK
qdrant.46.4.123.8.nip.io    /dashboard    HTTP_200
grafana.46.4.123.8.nip.io    /    REDIRECT_OK
headlamp.46.4.123.8.nip.io    /    HTTP_200
litmus.46.4.123.8.nip.io    /    HTTP_200
gitea.46.4.123.8.nip.io    /    HTTP_200
mlflow.46.4.123.8.nip.io    /    HTTP_200
jenkins.46.4.123.8.nip.io    /    HTTP_200_OR_403
awx.46.4.123.8.nip.io    /    HTTP_200_OR_REDIRECT
victoriametrics.46.4.123.8.nip.io    /    HTTP_200_OR_404
HOSTS

echo -e "host\tpath\texpected\tcode\tredirect_url\tcontent_type\tcurl_error\tresult" > "$OUT_DIR/web-results.tsv"

while IFS=$'\t' read -r host path expected; do
  [ -z "$host" ] && continue

  safe_host="${host//[^a-zA-Z0-9]/_}"
  safe_path="${path//[^a-zA-Z0-9]/_}"
  body="$OUT_DIR/body-${safe_host}-${safe_path}.txt"
  meta="$OUT_DIR/meta-${safe_host}-${safe_path}.txt"

  curl -k -sS -L --max-redirs 3 --connect-timeout 8 -m 20 \
    -o "$body" \
    -w '%{http_code}\t%{redirect_url}\t%{content_type}\t%{errormsg}' \
    "https://${host}${path}" > "$meta" 2>/dev/null || true

  code="$(awk -F'\t' '{print $1}' "$meta")"
  redirect_url="$(awk -F'\t' '{print $2}' "$meta")"
  content_type="$(awk -F'\t' '{print $3}' "$meta")"
  curl_error="$(awk -F'\t' '{print $4}' "$meta")"

  result="FAIL"

  case "$expected" in
    JSON_OK)
      grep -q '"status":"ok"' "$body" && grep -q '"collections"' "$body" && result="OK"
      ;;
    HTTP_200)
      [ "$code" = "200" ] && result="OK"
      ;;
    REDIRECT_OK)
      # -L follows redirects, so Grafana can end on login page with 200.
      { [ "$code" = "200" ] || [ "$code" = "302" ] || [ "$code" = "308" ]; } && result="OK"
      ;;
    HTTP_200_OR_403)
      { [ "$code" = "200" ] || [ "$code" = "403" ]; } && result="OK"
      ;;
    HTTP_200_OR_REDIRECT)
      { [ "$code" = "200" ] || [ "$code" = "302" ] || [ "$code" = "308" ]; } && result="OK"
      ;;
    HTTP_200_OR_404)
      { [ "$code" = "200" ] || [ "$code" = "404" ]; } && result="OK"
      ;;
  esac

  if grep -qi 'outpost.goauthentik.io/start' "$body" && [ "$expected" = "JSON_OK" ]; then
    result="FAIL_AUTH_REDIRECT_ON_JSON_API"
  fi

  echo -e "${host}\t${path}\t${expected}\t${code}\t${redirect_url}\t${content_type}\t${curl_error}\t${result}" >> "$OUT_DIR/web-results.tsv"
done < "$OUT_DIR/known-hosts.tsv"

python3 - "$OUT_DIR" <<'PY'
from pathlib import Path
import yaml
from collections import defaultdict
import sys

out = Path(sys.argv[1])
ing = out / "ingress-all.yaml"

items = []
if ing.exists() and ing.stat().st_size:
    obj = yaml.safe_load(ing.read_text()) or {}
    items = obj.get("items", [])

routes = defaultdict(list)
auth = []

auth_keys = [
    "nginx.ingress.kubernetes.io/auth-url",
    "nginx.ingress.kubernetes.io/auth-signin",
    "nginx.ingress.kubernetes.io/auth-response-headers",
    "nginx.ingress.kubernetes.io/auth-snippet",
    "nginx.ingress.kubernetes.io/configuration-snippet",
    "nginx.ingress.kubernetes.io/server-snippet",
    "nginx.ingress.kubernetes.io/enable-global-auth",
]

for i in items:
    meta = i.get("metadata", {})
    ns = meta.get("namespace", "")
    name = meta.get("name", "")
    ann = meta.get("annotations", {}) or {}

    if any(k in ann for k in auth_keys):
        auth.append(f"{ns}/{name}")

    for r in (i.get("spec", {}) or {}).get("rules", []) or []:
        host = r.get("host", "")
        for p in ((r.get("http", {}) or {}).get("paths", []) or []):
            path = p.get("path", "")
            svc = (((p.get("backend") or {}).get("service") or {}).get("name"))
            routes[(host, path)].append(f"{ns}/{name}->{svc}")

with (out / "ingress-collisions.tsv").open("w") as f:
    f.write("host\tpath\tcount\troutes\n")
    for (host, path), vals in sorted(routes.items()):
        if len(vals) > 1:
            f.write(f"{host}\t{path}\t{len(vals)}\t{vals}\n")

(out / "ingress-auth-list.txt").write_text("\n".join(auth) + "\n")
PY

WEB_FAILS="$(awk -F'\t' 'NR>1 && $8 !~ /^OK$/ {print}' "$OUT_DIR/web-results.tsv" | wc -l)"
INGRESS_COLLISIONS="$(awk 'NR>1 {print}' "$OUT_DIR/ingress-collisions.tsv" | wc -l)"

# Correct Flux READY check: count rows where READY column is not True, ignore SUSPENDED=False.
FLUX_NOT_READY="$(awk 'NR>1 && $5 != "True" {print}' "$OUT_DIR/flux-kustomizations.txt" | wc -l)"

echo
echo "===== WEB RESULTS ====="
cat "$OUT_DIR/web-results.tsv"

echo
echo "===== SUMMARY ====="
echo "WEB_FAILS=$WEB_FAILS"
echo "INGRESS_COLLISIONS=$INGRESS_COLLISIONS"
echo "FLUX_NOT_READY=$FLUX_NOT_READY"
echo "OUT_DIR=$OUT_DIR"

if [ "$WEB_FAILS" -eq 0 ] && [ "$INGRESS_COLLISIONS" -eq 0 ] && [ "$FLUX_NOT_READY" -eq 0 ]; then
  echo "SMOKE_STATUS=OK"
  exit 0
else
  echo "SMOKE_STATUS=FAIL"
  exit 2
fi
