"""Render the isolated demo's per-provider routes and WasmPlugin resources."""
import json
import sys

sha = sys.argv[1]
ns = "a2a-agent-demo"
providers = ["dify", "bailian", "coze", "qoder", "claude-managed"]
resources = []
for provider in providers:
    ingress = {
        "apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
        "metadata": {"name": provider, "namespace": ns, "annotations": {"higress.io/timeout": "120"}},
        "spec": {"ingressClassName": ns, "rules": [{"host": provider + ".agent.test", "http": {"paths": [{"path": "/", "pathType": "Prefix", "backend": {"service": {"name": "agent-fixture", "port": {"number": 8080}}}}]}}]},
    }
    config = {
        "provider": provider, "apiKey": "fixture-token",
        "agentId": "app-demo" if provider == "bailian" else "agent-demo",
        "consumerHeader": "x-agent-consumer",
        # Public demo constant. Production needs a secret, unique per exposure.
        "contextSecret": "demo-only-context-signing-key-32-characters",
        "agentCard": {"name": provider + " demo", "description": "Official-wire fixture; not a real hosted Agent", "url": "https://" + provider + ".agent.test/a2a", "version": "0.1.0", "skills": [{"id": "echo", "name": "Echo", "description": "Echo test messages", "tags": ["demo"]}]},
    }
    if provider in ("qoder", "claude-managed"):
        config.update(upstreamCluster="outbound|8080||agent-fixture.a2a-agent-demo.svc.cluster.local", upstreamAuthority="agent-fixture.a2a-agent-demo.svc.cluster.local:8080", upstreamScheme="http", sessionConfig={"environment_id": "env-demo"})
    resources.extend([ingress, {
        "apiVersion": "extensions.higress.io/v1alpha1", "kind": "WasmPlugin",
        "metadata": {"name": "a2a-to-" + provider, "namespace": ns},
        "spec": {"url": "http://agent-fixture.a2a-agent-demo.svc.cluster.local:8080/plugin.wasm?sha=" + sha, "sha256": sha, "phase": "UNSPECIFIED_PHASE", "priority": 100, "defaultConfigDisable": True, "matchRules": [{"ingress": [provider], "config": config}]},
    }])
# A separate route demonstrates that native API proxying remains available.
raw = json.loads(json.dumps(resources[0]))
raw["metadata"]["name"] = "raw-agent"
raw["spec"]["rules"][0]["host"] = "raw.agent.test"
resources.append(raw)
print(json.dumps({"apiVersion": "v1", "kind": "List", "items": resources}, indent=2))
