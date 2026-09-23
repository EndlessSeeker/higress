"""Exercise a real Higress gateway against deterministic Agent API fixtures."""
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18080"
providers = ["dify", "bailian", "coze", "qoder", "claude-managed"]
checks = []


def request(provider, payload=None, path="/a2a", consumer="demo-user"):
    headers = {"Host": provider + ".agent.test", "Content-Type": "application/json", "A2A-Version": "1.0"}
    if consumer:
        headers["x-agent-consumer"] = consumer
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        return urllib.request.urlopen(req, timeout=20)
    except urllib.error.HTTPError as error:
        return error


def message(text="你好 Agent", stream=True, context=None):
    msg = {"messageId": uuid.uuid4().hex, "role": "ROLE_USER", "parts": [{"text": text}]}
    if context:
        msg["contextId"] = context
    return {"jsonrpc": "2.0", "id": "demo-9007199254740993", "method": "SendStreamingMessage" if stream else "SendMessage", "params": {"message": msg}}


def run(provider, text="你好 Agent", stream=True, context=None, expected="TASK_STATE_COMPLETED", expected_answer=None):
    expected_answer = expected_answer if expected_answer is not None else "Echo: " + text
    start = time.monotonic()
    with request(provider, message(text, stream, context)) as response:
        assert response.status == 200, (provider, response.status, response.read())
        if not stream:
            body = json.load(response)
            assert body["id"] == "demo-9007199254740993", body
            task = body["result"]["task"]
            assert task["status"]["state"] == expected, task
            answer = "".join(p.get("text", "") for a in task.get("artifacts", []) for p in a["parts"])
            if expected == "TASK_STATE_COMPLETED":
                assert answer == expected_answer, answer
            checks.append(provider + ": blocking " + expected)
            return task.get("contextId")
        assert response.headers["Content-Type"].startswith("text/event-stream")
        answer = ""
        native_context = None
        first_output = None
        terminal = None
        progress = 0
        task_seen = False
        for line in response:
            if not line.startswith(b"data:"):
                continue
            body = json.loads(line[5:])
            assert body["jsonrpc"] == "2.0" and body["id"] == "demo-9007199254740993", body
            assert "error" not in body, body
            result = body["result"]
            assert len(result) == 1, result
            if "task" in result:
                task_seen = True
                native_context = result["task"].get("contextId")
            elif "artifactUpdate" in result:
                update = result["artifactUpdate"]
                native_context = update.get("contextId", native_context)
                chunk = "".join(p.get("text", "") for p in update["artifact"]["parts"])
                answer = answer + chunk if update.get("append") else chunk
                if chunk and first_output is None:
                    first_output = time.monotonic() - start
            elif "statusUpdate" in result:
                update = result["statusUpdate"]
                native_context = update.get("contextId", native_context)
                state = update["status"]["state"]
                if state in ("TASK_STATE_COMPLETED", "TASK_STATE_FAILED", "TASK_STATE_INPUT_REQUIRED"):
                    terminal = state
                    # Keep reading: A2A requires the server to close the stream.
                    # The native cloud fixture stays open indefinitely.
                progress += 1
        elapsed = time.monotonic() - start
        assert task_seen and terminal == expected, (provider, terminal, answer)
        assert elapsed < 10, (provider, "terminal stream did not close promptly", elapsed)
        if expected == "TASK_STATE_COMPLETED":
            assert answer == expected_answer, (provider, answer)
            assert first_output is not None and elapsed - first_output > .12, (provider, first_output, elapsed)
        assert native_context, (provider, "missing signed context")
        checks.append(provider + ": streaming " + expected + " (incremental)")
        return native_context


for provider in providers:
    with request(provider, path="/.well-known/agent-card.json", consumer=None) as response:
        card = json.load(response)
        assert response.status == 200, card
        assert card["supportedInterfaces"][0]["protocolVersion"] == "1.0", card
        assert card["capabilities"]["streaming"] is True
    checks.append(provider + ": Agent Card")
    context = run(provider)
    if provider in ("dify", "bailian", "coze"):
        run(provider, "续聊", context=context, expected_answer="Echo: 续聊 (previous: 你好 Agent)")
        run(provider, stream=False)
        run(provider, "FAIL", expected="TASK_STATE_FAILED")
        run(provider, "TRUNCATE", expected="TASK_STATE_FAILED")
        run(provider, "FAIL", stream=False, expected="TASK_STATE_FAILED")
        with request(provider, message(context=context), consumer="other-user") as response:
            assert "error" in json.load(response)
        checks.append(provider + ": cross-consumer context rejected")
    else:
        run(provider, "REQUIRE_ACTION", expected="TASK_STATE_INPUT_REQUIRED")
        run(provider, "PREFIX")
        with request(provider, message("SUBMIT_FAIL")) as response:
            assert response.status == 502 and "error" in json.load(response)
        checks.append(provider + ": message submission failure is JSON-RPC error before SSE")
        with request(provider, message(context=context)) as response:
            assert "error" in json.load(response)
        checks.append(provider + ": unsupported cloud continuation rejected")
    for payload in ({"jsonrpc": "2.0", "id": 1, "method": "CancelTask", "params": {"id": "unknown"}}, message()):
        with request(provider, payload, consumer=None) as response:
            assert response.status == 401
    with request(provider, {"jsonrpc": "2.0", "id": 1, "method": "GetTask", "params": {"id": "unknown"}}) as response:
        assert json.load(response)["error"]["code"] == -32601
    checks.append(provider + ": identity and unsupported method validation")

# Native Agent API on a second route remains unchanged.
with request("raw", {"query": "raw", "inputs": {}, "user": "demo", "response_mode": "blocking"}, path="/v1/chat-messages") as response:
    assert json.load(response)["answer"] == "Echo: raw"
checks.append("native HTTP route: unchanged")
print(json.dumps({"ok": True, "count": len(checks), "checks": checks}, ensure_ascii=False, indent=2))
