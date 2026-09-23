# A2A → Agent API demo

This demo runs the independent `a2a-to-agent` Wasm plugin in a real Higress
Kubernetes data path. Five deterministic HTTP services emulate the documented
Dify, Bailian Application, Coze, Qoder Cloud Agents and Claude Managed Agents
wire protocols. They do not execute real vendor agents or require vendor keys.
See the [plugin documentation](../../plugins/wasm-go/extensions/a2a-to-agent/README.md)
for configuration, supported operations and limitations.

A request follows this path:

```text
A2A client → Higress + a2a-to-agent → native Agent API
             ├─ Agent Card
             ├─ request / event conversion
             └─ session creation + subscribe-before-send for Cloud Agents
```

A separate `raw.agent.test` route has no conversion plugin, demonstrating that
native HTTP access and A2A access can coexist for the same backend. Five virtual
hosts each expose `/a2a` and `/.well-known/agent-card.json`.

## Reproduce

Use an isolated test Kubernetes cluster, Helm, kubectl, Python 3 and a Go 1.24+
toolchain. Run from the repository root. The demo installs Higress 2.2.4 with a
ClusterIP service, its CRDs and namespaced fixture resources. Use a dedicated
kubeconfig; the script does not select or change your current context.

```sh
kind create cluster --name a2a-agent-demo --image kindest/node:v1.34.0 \
  --kubeconfig /tmp/a2a-agent-demo.kubeconfig
export KUBECONFIG=/tmp/a2a-agent-demo.kubeconfig
(cd plugins/wasm-go/extensions/a2a-to-agent && \
  go test -count=1 ./... && go vet ./... && \
  GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o /tmp/a2a-to-agent.wasm .)
EVIDENCE_DIR=/tmp/a2a-agent-evidence \
  bash samples/a2a-to-agent/runtime/run.sh /tmp/a2a-to-agent.wasm
```

For the supplied development machine, kind uses rootful Podman through
`CONTAINER_HOST=unix:///run/podman/podman.sock KIND_EXPERIMENTAL_PROVIDER=podman`.
Its legacy cgroup v1 host also required creating the missing systemd cgroup
inside the **new demo node**, then restarting that node's kubelet during setup:

```sh
docker exec a2a-agent-demo-control-plane \
  mkdir -p /sys/fs/cgroup/systemd/kubelet.slice/kubelet-kubepods.slice
docker exec a2a-agent-demo-control-plane systemctl restart kubelet
```

These are environment-specific setup steps; do not run them against unrelated
clusters. Existing development clusters are not used by this demo.

`run.sh` copies the built Wasm module into the fixture pod and pins its SHA-256
in each WasmPlugin. HTTP module hosting is for this isolated test only. Use an
operator-controlled OCI image in production. `matchRules.ingress` uses the
Ingress name because this demo configures `global.watchNamespace`.

The demo's `x-agent-consumer` header and signing key are intentionally public
test constants, accessible through local port-forwarding. Production must
remove client-supplied identity headers and populate the configured header from
a trusted authentication plugin before this conversion plugin runs. Configure
real backend credentials and an independent random context signing secret.

## Verification

`runtime/verify.py` asserts Agent Card discovery, true incremental output,
terminal states and server EOF, synchronous aggregation, signed conversation
continuation for Dify/Bailian/Coze, identity separation, provider errors,
truncated SSE, rejected unsupported operations, and the unchanged native route.
Cloud fixtures reject messages before an SSE subscriber exists and keep their
SSE open after idle. The client reads until EOF, so success verifies that the
plugin itself ends the response. Cloud partial deltas are reconciled with final
messages; an HTTP 409 submission must return a JSON-RPC error before SSE starts.

Evidence includes assertions, server version, pod image digests, rendered
resources, Wasm hash and logs. Logs and generated Wasm files are not committed.
The script stops its temporary port-forward on exit and leaves the demo cluster
available for inspection. To invoke it manually:

```sh
kubectl -n a2a-agent-demo port-forward svc/higress-gateway 18080:80
# In another terminal:
python3 samples/a2a-to-agent/runtime/verify.py http://127.0.0.1:18080
```

Cleanup the dedicated cluster:

```sh
kind delete cluster --name a2a-agent-demo
```

## Platform selection

Dify and Bailian cover application-oriented agents; Qoder and Claude Managed
Agents cover managed coding runtimes. Coze adds another established
application ecosystem with a documented Agent API. This is a choice based on
API availability and ecosystem relevance, not a claim of measured market
share. LangGraph and AgentScope can expose graph/application-specific schemas;
they belong in the later schema-driven phase requested by the user.

Official references: [Dify](https://github.com/langgenius/dify/blob/1.9.2/web/app/components/develop/template/template_chat.en.mdx),
[Bailian Agent 2.0](https://help.aliyun.com/zh/model-studio/new-agent-application-api-reference),
[Coze SDK](https://github.com/coze-dev/coze-py/blob/main/cozepy/chat/__init__.py),
[Qoder API](https://docs.qoder.com/cloud-agents/api-overview),
[Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents/reference),
[A2A 1.0 wire schema](https://github.com/a2aproject/A2A/blob/v1.0.0/specification/a2a.proto).
