"""Minimal OpenAI-compatible mock for offline checks: python tests/mock_server.py (port 1234)."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        self._send({"data": [{"id": "qwen3.5-9b", "object": "model"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        rf = req.get("response_format")
        if rf and rf["type"] == "json_schema":
            n = rf["json_schema"]["name"]
            text = {"module_router": '{"module_code":"SZ","confidence":0.9}',
                    "field_extractor": '{"fields":{"addressee":"Иванов"},"missing":[]}'}.get(n, "{}")
        else:
            text = "<think>hmm</think>Срок — 3 дня [п. 10.6]."
        if req.get("stream"):
            self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.end_headers()
            for i in range(0, len(text), 5):
                c = {"choices": [{"index": 0, "delta": {"content": text[i:i + 5]}}]}
                self.wfile.write(f"data: {json.dumps(c)}\n\n".encode())
            u = {"choices": [], "usage": {"prompt_tokens": 100, "completion_tokens": len(text) // 3, "total_tokens": 0}}
            self.wfile.write(f"data: {json.dumps(u)}\n\ndata: [DONE]\n\n".encode())
        else:
            self._send({"id": "x", "object": "chat.completion", "created": 0, "model": "m",
                        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": text}}],
                        "usage": {"prompt_tokens": 50, "completion_tokens": 20, "total_tokens": 70}})


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 1234), H).serve_forever()
