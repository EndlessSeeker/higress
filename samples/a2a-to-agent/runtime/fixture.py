"""Deterministic official-wire fixtures, not real hosted Agents.

Only for isolated demo namespaces. No credentials or external services are used.
Cloud SSE deliberately stays open after idle to exercise A2A client termination.
"""
import json
import queue
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sessions = {}
lock = threading.Lock()


def identifier(prefix):
    return prefix + uuid.uuid4().hex


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        # Never log request bodies or authentication headers.
        print(fmt % args, flush=True)

    def reply(self, body, status=200, content_type="application/json"):
        payload = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def stream_headers(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.flush()

    def event(self, data, event=None):
        payload = "data: " + (data if isinstance(data, str) else json.dumps(data, ensure_ascii=False))
        if event:
            payload = "event: " + event + "\r\n" + payload
        wire = (payload + "\r\n\r\n").encode()
        # Fragment on arbitrary bytes, including UTF-8 and CRLF boundaries.
        for offset in range(0, len(wire), 17):
            self.wfile.write(wire[offset:offset + 17])
            self.wfile.flush()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.reply({"ok": True})
        if path == "/plugin.wasm":
            file = Path("/data/plugin.wasm")
            return self.reply(file.read_bytes(), content_type="application/wasm") if file.exists() else self.reply({}, 404)
        if path.endswith("/events/stream"):
            sid = path.split("/")[-3]
            with lock:
                state = sessions.get(sid)
                if state is None:
                    return self.reply({"error": "session not found"}, 404)
                channel = queue.Queue()
                state["subscribers"].append(channel)
            self.stream_headers()
            try:
                # Flush a comment so the proxy has observable SSE headers.
                self.wfile.write(b": connected\n\n")
                self.wfile.flush()
                while True:
                    try:
                        kind, value = channel.get(timeout=1)
                        self.event(value, kind)
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with lock:
                    state["subscribers"].remove(channel)
            return
        self.reply({"error": "unknown path"}, 404)

    def do_POST(self):
        try:
            if self.headers.get("Transfer-Encoding", "").lower() == "chunked":
                chunks = []
                while True:
                    size = int(self.rfile.readline().split(b";", 1)[0], 16)
                    if size == 0:
                        while self.rfile.readline().strip():
                            pass
                        break
                    chunks.append(self.rfile.read(size))
                    self.rfile.read(2)
                raw = b"".join(chunks)
            else:
                raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            body = json.loads(raw)
        except (ValueError, json.JSONDecodeError):
            return self.reply({"error": "invalid json"}, 400)
        path = urlparse(self.path).path
        if path.endswith("/sessions"):
            if not body.get("agent") or not body.get("environment_id"):
                return self.reply({"error": "agent and environment_id required"}, 400)
            sid = identifier("sess_")
            with lock:
                sessions[sid] = {"subscribers": [], "turn": 0}
            return self.reply({"id": sid, "type": "session", "status": "idle"})
        if path.endswith("/events"):
            sid = path.split("/")[-2]
            with lock:
                state = sessions.get(sid)
                if not state:
                    return self.reply({"error": "session not found"}, 404)
                if not state["subscribers"]:
                    return self.reply({"error": "fixture requires subscription before send"}, 409)
                events = body.get("events", [])
                if len(events) != 1 or events[0].get("type") != "user.message":
                    return self.reply({"error": "user.message required"}, 400)
                text = events[0]["content"][0]["text"]
                if "SUBMIT_FAIL" in text:
                    return self.reply({"error": "fixture message rejected"}, 409)
                state["turn"] += 1
                channels = list(state["subscribers"])
                turn = state["turn"]
            self.reply({"data": [{"id": identifier("evt_"), **events[0]}]})
            threading.Thread(target=self.cloud, args=(channels, text, turn), daemon=True).start()
            return
        if path == "/v1/chat-messages":
            if not body.get("user") or "query" not in body or "inputs" not in body:
                return self.reply({"error": "missing dify fields"}, 400)
            query = body["query"]
            sid = body.get("conversation_id") or identifier("conv_")
            common = {"conversation_id": sid, "message_id": "dm1", "task_id": "dt1"}
            if body.get("response_mode") == "blocking":
                return self.reply({**common, "event": "message", "answer": "Echo: " + query})
            self.stream_headers()
            self.event({**common, "event": "agent_thought", "id": "thought1", "position": 1, "thought": "Planning", "tool": "search", "tool_input": "{}", "observation": "found"})
            self.event({**common, "event": "agent_message", "answer": "Echo: " + query})
            time.sleep(.25)
            if "TRUNCATE" in query:
                self.close_connection = True
                return
            if "FAIL" in query:
                self.event({"event": "error", "status": 500, "code": "internal_server_error", "message": "fixture failure"})
            else:
                self.event({**common, "event": "message_end", "metadata": {"usage": {"total_tokens": 10}}})
            self.close_connection = True
            return
        if path == "/api/v1/apps/app-demo/completion":
            query = body.get("input", {}).get("prompt")
            if query is None:
                return self.reply({"code": "InvalidParameter", "message": "input.prompt required"}, 400)
            sid = body["input"].get("session_id") or identifier("bailian_")
            def output(text, finish="null", **extra):
                return {"output": {"text": text, "session_id": sid, "finish_reason": finish, **extra}, "request_id": "br1"}
            if self.headers.get("X-DashScope-SSE") != "enable":
                return self.reply(output("Echo: " + query, "stop"))
            self.stream_headers()
            self.event(output("", thoughts=[{"thought": "Planning", "action_type": "API", "action_name": "search", "action_input": "{}", "observation": "found"}]))
            self.event(output("Echo: " + query))
            time.sleep(.25)
            if "TRUNCATE" not in query:
                self.event({"code": "InvalidApiKey", "message": "fixture failure"} if "FAIL" in query else output("", "stop"))
            self.close_connection = True
            return
        if path == "/v3/chat":
            if not body.get("bot_id") or not body.get("user_id") or not body.get("stream"):
                return self.reply({"code": 400, "msg": "streaming bot/user required"}, 400)
            from urllib.parse import parse_qs
            sid = parse_qs(urlparse(self.path).query).get("conversation_id", [identifier("coze_")])[0]
            query = body["additional_messages"][0]["content"]
            chat = {"id": "ct1", "conversation_id": sid, "bot_id": body["bot_id"]}
            msg = {"id": "cm1", "conversation_id": sid, "chat_id": "ct1", "role": "assistant", "type": "answer", "content": "Echo: " + query, "content_type": "text"}
            self.stream_headers()
            self.event({**chat, "status": "created"}, "conversation.chat.created")
            self.event(msg, "conversation.message.delta")
            self.event(msg, "conversation.message.completed")
            time.sleep(.25)
            if "TRUNCATE" not in query:
                if "FAIL" in query:
                    self.event({**chat, "status": "failed", "last_error": {"code": 500, "msg": "fixture failure"}}, "conversation.chat.failed")
                else:
                    self.event({**chat, "status": "completed", "usage": {"token_count": 10}}, "conversation.chat.completed")
                self.event("[DONE]", "done")
            self.close_connection = True
            return
        self.reply({"error": "unknown path"}, 404)

    @staticmethod
    def cloud(channels, text, turn):
        def emit(kind, data):
            for channel in channels:
                channel.put((kind, data))
        eid = identifier("evt_")
        answer = "Echo: " + text
        emit("session.status_running", {"type": "session.status_running"})
        emit("agent.thinking", {"id": identifier("evt_"), "type": "agent.thinking"})
        emit("event_start", {"type": "event_start", "event": {"id": eid, "type": "agent.message"}})
        emit("event_delta", {"type": "event_delta", "event_id": eid, "delta": {"type": "content_delta", "index": 0, "content": {"type": "text", "text": answer[:3] if "PREFIX" in text else answer}}})
        time.sleep(.25)
        emit("agent.message", {"id": eid, "type": "agent.message", "content": [{"type": "text", "text": answer}]})
        # Child idle must not complete the root task.
        emit("session.thread_status_idle", {"type": "session.thread_status_idle", "thread_id": "child-1"})
        reason = "requires_action" if "REQUIRE_ACTION" in text else "end_turn"
        emit("session.status_idle", {"type": "session.status_idle", "stop_reason": {"type": reason}})


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
