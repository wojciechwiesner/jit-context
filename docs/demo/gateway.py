"""Recording proxy: forward real provider replies, retain only metrics (no prompt/key)."""

import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import threading
from urllib.parse import urlsplit


def stream_completion(result):
    """Frame the unmodified provider content and tool calls as OpenAI SSE."""
    base = {k: result[k] for k in ('id', 'created', 'model') if k in result}
    base['object'] = 'chat.completion.chunk'
    chunks = []
    for choice in result.get('choices', []):
        delta = {k: v for k, v in choice['message'].items() if v is not None}
        for index, tool in enumerate(delta.get('tool_calls', [])):
            tool['index'] = index
        chunks.append({**base, 'choices': [{'index': choice['index'], 'delta': delta, 'finish_reason': None}]})
        chunks.append({**base, 'choices': [{'index': choice['index'], 'delta': {},
                                            'finish_reason': choice.get('finish_reason')}]})
    if result.get('usage'):
        chunks.append({**base, 'choices': [], 'usage': result['usage']})
    return (''.join(f'data: {json.dumps(chunk)}\n\n' for chunk in chunks) + 'data: [DONE]\n\n').encode()


def open_gateway(url, key, log, call_limit, tools, expected_scope, *, offline=False):
    upstream = urlsplit(url)
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers['Content-Length']))
            data = json.loads(raw)
            if self.path.rstrip('/') != '/v1/chat/completions':
                return self.reply(404, b'{"error":{"message":"Unexpected endpoint"}}')
            message_bytes = json.dumps(data.get('messages', []), ensure_ascii=False).encode()
            scope = re.search(rb'<ONA_CONTEXT\s+scope=[\\]*"([^"\\]+)', message_bytes)
            with lock:
                if len(log) >= call_limit:
                    return self.reply(429, b'{"error":{"message":"Demo call budget exhausted"}}')
                if len(raw) > 85_000:
                    return self.reply(422, b'{"error":{"message":"Demo input byte budget exhausted"}}')
                if not tools and data.get('tools'):
                    return self.reply(422, b'{"error":{"message":"Unexpected tools in no-tools arm"}}')
                entry = {'capsule_scope': scope[1].decode() if scope else None,
                         'tool_count': len(data.get('tools') or []), 'input_bytes': len(raw),
                         'requested_model': data['model']}
                log.append(entry)
            if len(log) == 1 and entry['capsule_scope'] != expected_scope:
                entry['status'] = 422
                return self.reply(422, b'{"error":{"message":"First request failed the JIT scope check"}}')
            if offline:
                entry['status'] = 400
                return self.reply(400, b'{"error":{"message":"Offline preflight stopped before inference"}}')
            wants_stream = data.get('stream') is True
            data.update(stream=False, max_tokens=2048)
            data.pop('stream_options', None)
            if upstream.hostname == 'openrouter.ai':
                data.pop('reasoning_effort', None)
                data.update(reasoning={'effort': 'none'}, provider={'allow_fallbacks': False})
            elif upstream.hostname == 'generativelanguage.googleapis.com':
                data.pop('reasoning_effort', None)
                # Google's compatibility layer does not accept every JSON-Schema extension.
                for tool in data.get('tools', []):
                    params = tool['function'].get('parameters', {})
                    params.pop('additionalProperties', None)
            else:
                data.pop('reasoning', None)
                data['think'] = False
            conn_cls = http.client.HTTPSConnection if upstream.scheme == 'https' else http.client.HTTPConnection
            conn = conn_cls(upstream.hostname, upstream.port, timeout=180)
            try:
                headers = {'Content-Type': 'application/json'}
                if key:
                    headers['Authorization'] = f'Bearer {key}'
                conn.request('POST', upstream.path + '/chat/completions', json.dumps(data), headers)
                response = conn.getresponse()
                body = response.read()
                result = json.loads(body)
                if isinstance(result, list) and len(result) == 1 and isinstance(result[0], dict):
                    result = result[0]
                    body = json.dumps(result).encode()
                info = result if isinstance(result, dict) else {}
                entry.update(status=response.status, usage=info.get('usage'), response_model=info.get('model'))
                if wants_stream and response.status == 200:
                    return self.reply(200, stream_completion(info), 'text/event-stream')
                self.reply(response.status, body)
            except (OSError, ValueError, http.client.HTTPException) as exc:
                entry['error'] = type(exc).__name__
                self.reply(502, json.dumps({'error': {'message': str(exc)}}).encode())
            finally:
                conn.close()

        def reply(self, status, body, content_type='application/json'):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
