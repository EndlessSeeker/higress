#!/usr/bin/env bash
# Run from the repository root with KUBECONFIG pointing at an isolated cluster.
set -euo pipefail
: "${KUBECONFIG:?Set KUBECONFIG to the demo cluster config}"
WASM_FILE=${1:?Usage: run.sh /absolute/path/plugin.wasm}
DEMO_PORT=${DEMO_PORT:-18080}
EVIDENCE_DIR=${EVIDENCE_DIR:-/tmp/a2a-to-agent-evidence}
mkdir -p "$EVIDENCE_DIR"
RUNTIME_DIR=samples/a2a-to-agent/runtime
if command -v sha256sum >/dev/null; then
  WASM_SHA=$(sha256sum "$WASM_FILE" | cut -d ' ' -f1)
else
  WASM_SHA=$(shasum -a 256 "$WASM_FILE" | cut -d ' ' -f1)
fi
helm upgrade --install a2a-agent-demo ./helm/core --namespace a2a-agent-demo --create-namespace \
  -f "$RUNTIME_DIR/values.yaml" --wait --timeout 5m
kubectl create configmap agent-fixture-code -n a2a-agent-demo \
  --from-file=fixture.py="$RUNTIME_DIR/fixture.py" --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -f "$RUNTIME_DIR/fixture.yaml"
kubectl rollout restart deployment/agent-fixture -n a2a-agent-demo
kubectl rollout status deployment/agent-fixture -n a2a-agent-demo --timeout=120s
FIXTURE_POD=$(kubectl get pod -n a2a-agent-demo -l app=agent-fixture -o json | python3 -c 'import json,sys; print(next(p["metadata"]["name"] for p in json.load(sys.stdin)["items"] if not p["metadata"].get("deletionTimestamp")))')
kubectl cp "$WASM_FILE" "a2a-agent-demo/$FIXTURE_POD:/data/plugin.wasm"
kubectl exec -n a2a-agent-demo "$FIXTURE_POD" -- sha256sum /data/plugin.wasm > "$EVIDENCE_DIR/wasm.sha256"
python3 "$RUNTIME_DIR/render.py" "$WASM_SHA" > "$EVIDENCE_DIR/resources.json"
kubectl apply -f "$EVIDENCE_DIR/resources.json"
kubectl rollout restart deployment/higress-gateway -n a2a-agent-demo
kubectl rollout status deployment/higress-gateway -n a2a-agent-demo --timeout=120s
kubectl port-forward -n a2a-agent-demo svc/higress-gateway "$DEMO_PORT:80" > "$EVIDENCE_DIR/port-forward.log" 2>&1 &
FORWARD_PID=$!
trap 'kill "$FORWARD_PID" 2>/dev/null || true; wait "$FORWARD_PID" 2>/dev/null || true' EXIT
READY=false
for attempt in $(seq 1 30); do
  if curl --noproxy '*' -fsS --max-time 1 -H 'Host: dify.agent.test' \
    "http://127.0.0.1:$DEMO_PORT/.well-known/agent-card.json" > "$EVIDENCE_DIR/agent-card.json"; then
    READY=true
    break
  fi
  sleep 1
done
if [[ "$READY" != true ]]; then
  kubectl logs -n a2a-agent-demo deployment/higress-gateway --tail=80 >&2
  exit 1
fi
python3 "$RUNTIME_DIR/verify.py" "http://127.0.0.1:$DEMO_PORT" | tee "$EVIDENCE_DIR/results.json"
kubectl get --raw /version > "$EVIDENCE_DIR/kubernetes-version.json"
kubectl get pods -n a2a-agent-demo -o json > "$EVIDENCE_DIR/pods.json"
kubectl logs -n a2a-agent-demo deployment/higress-gateway > "$EVIDENCE_DIR/gateway.log"
kubectl logs -n a2a-agent-demo "$FIXTURE_POD" > "$EVIDENCE_DIR/fixture.log"
