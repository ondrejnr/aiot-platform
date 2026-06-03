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

echo -e "host\tpath\texpected\tcode\tlocation\tcontent_type\tresult" > "$OUT_DIR/web-results.tsv"

while IFS=$'\t' read -r host path expected; do
  [ -z "$host" ] && continue
  tmp="$OUT_DIR/resp-${host//[^a-zA-Z0-9]/_}-${path//[^a-zA-Z0-9]/_}.txt"

  curl -k -sS -i -m 15 "https://${host}${path}" > "$tmp" 2>/dev/null || true

  code="$(awk 'BEGIN{c=""} /^HTTP\//{c=$2} END{print c}' "$tmp")"
  loc="$(awk 'BEGIN{IGNORECASE=1} /^location:/{sub(/\r/,""); print substr($0, index($0,$2)); exit}' "$tmp")"
  ctype="$(awk 'BEGIN{IGNORECASE=1} /^content-type:/{sub(/\r/,""); print substr($0, index($0,$2)); exit}' "$tmp")"

  result="FAIL"

  case "$expected" in
    JSON_OK)
      grep -q '"status":"ok"' "$tmp" && grep -q '"collections"' "$tmp" && result="OK"
      ;;
    HTTP_200)
      [ "$code" = "200" ] && result="OK"
      ;;
    REDIRECT_OK)
      { [ "$code" = "302" ] || [ "$code" = "308" ] || [ "$code" = "200" ]; } && result="OK"
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

  if grep -qi 'outpost.goauthentik.io/start' "$tmp" && [ "$expected" = "JSON_OK" ]; then
    result="FAIL_AUTH_REDIRECT_ON_JSON_API"
  fi

  echo -e "${host}\t${path}\t${expected}\t${code}\t${loc}\t${ctype}\t${result}" >> "$OUT_DIR/web-results.tsv"
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

FAILS="$(awk -F'\t' 'NR>1 && $7 !~ /^OK$/ {print}' "$OUT_DIR/web-results.tsv" | wc -l)"
COLLISIONS="$(awk 'NR>1 {print}' "$OUT_DIR/ingress-collisions.tsv" | wc -l)"
FLUX_FALSE="$(grep -E '\sFalse\s' "$OUT_DIR/flux-kustomizations.txt" | wc -l)"

echo
echo "===== WEB RESULTS ====="
cat "$OUT_DIR/web-results.tsv"

echo
echo "===== SUMMARY ====="
echo "WEB_FAILS=$FAILS"
echo "INGRESS_COLLISIONS=$COLLISIONS"
echo "FLUX_FALSE=$FLUX_FALSE"
echo "OUT_DIR=$OUT_DIR"

if [ "$FAILS" -eq 0 ] && [ "$COLLISIONS" -eq 0 ] && [ "$FLUX_FALSE" -eq 0 ]; then
  echo "SMOKE_STATUS=OK"
  exit 0
else
  echo "SMOKE_STATUS=FAIL"
  exit 2
fi
