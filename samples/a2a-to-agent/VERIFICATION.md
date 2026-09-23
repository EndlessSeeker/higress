# Verification: A2A to Agent API

Date: 2026-09-23. Result: **42 runtime assertions passed** through a real
Higress gateway in an isolated kind cluster. The user changed the requested
runtime environment from ACK to the supplied development machine's kind
cluster, and confirmed no vendor application credentials were available.
Therefore these results validate the gateway and official-wire fixtures, **not
live Dify/Bailian/Coze/Qoder/Claude services or ACK acceptance**.

## Exact inputs

- Base: `a42482341eb199b2c1553a560c81137ebad14441` (fresh upstream main).
- Plugin source: `807e041ce2dd7a6153e582d66e28b5d5de5b4469`.
- Tested repository/demo revision: `49c2ad36c80182cdc8a2369067a4885b61b3ee09`.
- Go: `go1.24.1 darwin/arm64`, compiled for `wasip1/wasm` with `c-shared`.
- Runtime: Linux amd64, kind `v0.32.0`, Kubernetes `v1.34.0`, rootful Podman.
- Higress chart and component tags: `2.2.4` / `v2.2.4`.
- Gateway resolved digest:
  `higress-registry.cn-hangzhou.cr.aliyuncs.com/higress/gateway@sha256:3dbd609df5db3fca61653eafe0e2310705e485190c4f8cd02d9aab8f07dcf329`.
- Pilot digest: `sha256:f742ed20f938c5c1eaf6f8c36c6481a87052d06e903ab6cb0c079165ac0c8284`.
- Controller digest: `sha256:0a5b7809a107cbec150f41352a156e31160b8a92df787798e2a9a06cdd5587da`.
- Python fixture digest: `sha256:4c47124a8391cb7a9f571164147d154777cf012a4ece5f86097130d7a4478111`.
- Wasm SHA-256: `6e03d6222235c97f0b4b54d08fa2ada6e180c747ee730a5132aa16e7ea7757c8`.
- Configuration: [values.yaml](runtime/values.yaml),
  [fixture.yaml](runtime/fixture.yaml), [render.py](runtime/render.py).
  The rendered WasmPlugin resources pin the exact Wasm hash.

## Commands and outcomes

From `plugins/wasm-go/extensions/a2a-to-agent`:

```sh
go test -count=1 ./...
go vet ./...
GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared \
  -o /tmp/a2a-to-agent-807e041.wasm .
```

All returned exit 0. Tests include native request mapping, authenticated context
isolation, bounded SSE parsing, provider terminal/error handling, snapshot
reconciliation and SDK host-emulator callback ordering.

On the development machine, from its dedicated `a2a-to-agent-demo` workspace:

```sh
export KUBECONFIG="$PWD/kubeconfig"
export EVIDENCE_DIR="$PWD/evidence-final"
export DEMO_PORT=18081
bash samples/a2a-to-agent/runtime/run.sh "$PWD/plugin.wasm"
```

Exit 0; `results.json` reports `ok: true`, `count: 42`. This covers:

- All five Agent Cards and A2A streaming responses with incremental text and
  matching JSON-RPC IDs.
- Dify/Bailian/Coze blocking aggregation, history-dependent continuation,
  upstream failures, truncated SSE failures, cross-consumer context rejection.
- Qoder/CMA subscribe-before-send ordering, incomplete delta preview repair,
  provider HTTP 409 before downstream SSE, `requires_action`, and explicit
  rejection of unsupported cloud continuation.
- Server-side EOF after terminal/interrupted status even though cloud fixture
  SSE remains open indefinitely. The client does not close early to pass.
- Missing identity, unsupported methods, and native HTTP passthrough on a
  separate route.

The test enforces at least 120 ms between first answer data and terminal EOF.
A known first-turn message must appear in continuation output; merely starting
another session cannot satisfy the assertion. Port occupancy and the newly
started port-forward process are checked to prevent testing an older gateway.

## Evidence hashes

Raw artifacts are retained in the development workspace's `evidence-final/`,
with a local copy supplied alongside this work. They are not committed because
they include generated runtime logs and resource snapshots.

| Artifact | SHA-256 |
|---|---|
| `results.json` | `7fafcf1c5313663df2b1cb8f6c6b6687ce9d73918ac0ae99d83f69b8e9251186` |
| `resources.json` | `626f194b23621c41a49ee4c0e54cca70a6566fedd1943377ea7d662cf1b26864` |
| `gateway.log` | `97cc6a3a90e1850234cf83091fdcd2d13419b9e4e5aac2628621f7eae9b8d703` |
| `fixture.log` | `8c92586dce692124f66c4bb2749d282b86a7c30837c81f6eece052956c3f0c6f` |
| `pods.json` | `deb9de7cef83aeaa4b286305deb5fd955d8d62db7a014ca911a3cf239e901383` |

Independent read-only review of plugin commit `807e041` and demo commit
`49c2ad36` reported no remaining actionable P0/P1/P2 findings after repairs.
This does not replace human review or live vendor interoperation.

## Environment disposition

The three demo pods are Running; the dedicated kind cluster is left available
for inspection. Temporary test forwards on 18080/18081 are closed. Existing
kind clusters were not changed. The temporary ACK release, namespace and the
four otherwise-empty CRDs created by that release were removed after the user
selected kind instead.

See [README](README.md) for rerun, manual access and dedicated-cluster cleanup.
No plugin binary, production credential, public image, or deployment is
published by this change. The original `a2a-protocol` work is untouched.
