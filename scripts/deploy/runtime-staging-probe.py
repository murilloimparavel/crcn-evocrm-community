#!/usr/bin/env python3
"""Synthetic in-network runtime probe. Mock AI/postback; no LLM or customer calls."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
import urllib.request
import uuid

calls, replies = [], []
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def do_POST(self):
        value = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.path == '/a2a/mock':
            calls.append(value)
            body = {'jsonrpc': '2.0', 'result': {'artifacts': [{'parts': [{'type': 'text', 'text': 'synthetic QA response'}]}]}}
        elif self.path == '/postback':
            replies.append(value)
            body = {'status': 'sent'}
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())


def main():
    server = ThreadingHTTPServer(('0.0.0.0', 18999), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    ids = [str(uuid.uuid4()) for _ in range(3)]
    contact, conversation = int(time.time() * 1000), int(time.time() * 1000) + 1
    messages = ['Quero valores', '5 adultos', 'Entrada 20/11 e saída 23/11']
    events = []
    try:
        for identifier, text in zip(ids, messages):
            event = {'agent_bot_id': 'synthetic-qa', 'contact_id': contact, 'conversation_id': conversation,
                     'message_id': identifier, 'message_content': text, 'api_key': 'synthetic-only',
                     'outgoing_url': 'http://evocrm_processor:18999/a2a/mock',
                     'postback_url': 'http://evocrm_processor:18999/postback', 'bot_config': {'debounce_time': 2}}
            events.append(event)
        def send(event):
            request = urllib.request.Request('http://evocrm_bot_runtime:8080/events', data=json.dumps(event).encode(),
                headers={'Content-Type': 'application/json', 'X-Bot-Runtime-Secret': os.environ['QA_BOT_SECRET']})
            with urllib.request.urlopen(request, timeout=10) as result:
                if result.status != 202:
                    raise RuntimeError('Runtime did not durably accept QA event')
        for event in events:
            send(event)
        send(events[-1])
        deadline = time.monotonic() + 45
        while not replies and time.monotonic() < deadline:
            time.sleep(0.1)
        if len(calls) != 1 or len(replies) != 1:
            raise RuntimeError('Burst/dedup failed')
        request = calls[0]['params']['message']
        text = '\n'.join(p.get('text', '') for p in request['parts'])
        if not all(value in text for value in messages):
            raise RuntimeError('A provided fact disappeared from the batch')
        batch = 'debounce:' + hashlib.sha256(b''.join(v.encode() + b'\0' for v in sorted(ids))).hexdigest()
        if request['messageId'] != batch or not replies[0].get('runtime_delivery_id', '').startswith(batch + ':'):
            raise RuntimeError('Message provenance/dispatch ID mismatch')
        send(events[-1])
        time.sleep(3)
        if len(calls) != 1 or len(replies) != 1:
            raise RuntimeError('Completed event was processed again')
        print(json.dumps({'synthetic_runtime_probe': True, 'all_three_facts_preserved': True,
                          'dedup_verified': True, 'ai_calls': len(calls), 'postbacks': len(replies)}))
    finally:
        server.shutdown()


if __name__ == '__main__':
    main()
