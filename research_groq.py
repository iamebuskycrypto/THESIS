"""Session-only Groq research client. Never used by the paper decision engine."""
from __future__ import annotations
import copy
import json
import math
import re
import threading
import time
import urllib.error
import urllib.request

MODEL = 'openai/gpt-oss-120b'
ENDPOINT = 'https://api.groq.com/openai/v1/chat/completions'


def provider_schema(value):
    # Local validators retain these constraints, including limits on source IDs.
    if isinstance(value, dict):
        return {k: provider_schema(v) for k, v in value.items()
                if k not in ('minLength', 'maxLength', 'minItems', 'maxItems')}
    if isinstance(value, list):
        return [provider_schema(v) for v in value]
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Groq redirected the request. The key was not forwarded.')


class GroqResearch:
    endpoint, model, local = ENDPOINT, MODEL, False
    grounding_profile = True

    def __init__(self, key, opener=None, clock=time.monotonic, wall_clock=time.time):
        if not isinstance(key, str) or not 20 <= len(key.strip()) <= 500:
            raise ValueError('Paste a complete Groq API key.')
        key = key.strip()
        if not key.isascii() or any(c.isspace() for c in key):
            raise ValueError('The key contains unexpected characters. Copy only the key.')
        self._secret = key
        self._opener = opener or urllib.request.build_opener(NoRedirect())
        self._clock, self._wall_clock = clock, wall_clock
        self._next_request = 0.0
        self._lock = threading.Lock()
        self.last_successful_at = None
        self.last_response_metadata = None

    @property
    def request_settings(self):
        return {'adapter_version': 'groq-research-080', 'max_completion_tokens': 4096,
                'reasoning_effort': 'medium', 'include_reasoning': False,
                'timeout_seconds': 90, 'minimum_request_interval_seconds': 60,
                'automatic_retries': 0}

    def response_format(self, schema, name):
        return {'type': 'json_schema', 'json_schema': {
            'name': name, 'strict': True, 'schema': provider_schema(schema)}}

    def cooldown_seconds(self):
        return max(0, math.ceil(self._next_request - self._clock()))

    def require_ready(self):
        wait = self.cooldown_seconds()
        if wait:
            raise ValueError(f'Groq research is ready for another request in {wait} seconds.')

    def snapshot(self):
        return {'provider': 'groq', 'configured': True, 'model': self.model,
                'connection_tested': self.last_successful_at is not None,
                'last_successful_at': self.last_successful_at,
                'cooldown_seconds': self.cooldown_seconds(), 'scope': 'research_only'}

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self._secret, '[REDACTED]')
        if isinstance(value, dict):
            return {self.redact(k): self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def _request(self, supplied):
        with self._lock:
            self.require_ready()
            self._next_request = self._clock() + 60
            self.last_response_metadata = None
            fmt = supplied.get('response_format', {})
            if fmt.get('type') != 'json_schema':
                raise ValueError('This research request requires its explicit output schema.')
            payload = {'model': MODEL, 'messages': copy.deepcopy(supplied['messages']),
                       'response_format': provider_schema(fmt), 'stream': False,
                       'max_completion_tokens': 4096, 'reasoning_effort': 'medium',
                       'include_reasoning': False}
            raw = json.dumps(payload, ensure_ascii=False).encode()
            if len(raw) > 60000:
                raise ValueError('The research request is too large. No source text was silently removed.')
            request = urllib.request.Request(ENDPOINT, data=raw, method='POST', headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self._secret,
                'User-Agent': 'THESIS-Research/0.8.0'})
            try:
                with self._opener.open(request, timeout=90) as response:
                    body = response.read(1_000_001)
                if len(body) > 1_000_000:
                    raise ValueError('Groq response exceeded the response size limit.')
                data = json.loads(body)
            except urllib.error.HTTPError as exc:
                status = exc.code
                retry_after = exc.headers.get('Retry-After') if exc.headers else None
                exc.close()  # Never echo provider error bodies, headers or credentials.
                if status == 429 and retry_after:
                    try:
                        wait = float(retry_after)
                        if math.isfinite(wait) and wait > 0:
                            self._next_request = max(self._next_request, self._clock() + min(wait, 86400))
                    except ValueError:
                        pass
                message = {400: 'Groq rejected this research request.',
                    401: 'Groq rejected the key. Replace it in the research connection panel.',
                    403: 'This Groq key cannot access the selected model.',
                    404: 'The selected Groq model is unavailable.',
                    429: 'Groq rate or quota limit reached. Wait before another request; check your free-plan quota if it persists.',
                    503: 'Groq is temporarily unavailable. The source brief remains saved.'}.get(status, 'Groq could not complete this request.')
                raise ValueError(f'{message} HTTP {status}. No automatic retry.') from None
            except (urllib.error.URLError, TimeoutError, OSError):
                raise ValueError('Could not complete the Groq connection. No automatic retry; the source brief remains saved.') from None
            except (json.JSONDecodeError, UnicodeError):
                raise ValueError('Groq did not return a readable response.') from None
            if not isinstance(data, dict):
                raise ValueError('Groq did not return a completion object.')
            choices = data.get('choices')
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError('Groq did not return exactly one answer.')
            choice = choices[0]
            if choice.get('finish_reason') != 'stop':
                raise ValueError('The Groq answer stopped before normal completion. No draft accepted.')
            message = choice.get('message')
            if (not isinstance(message, dict) or message.get('role') != 'assistant'
                    or message.get('refusal') or message.get('tool_calls') or message.get('function_call')):
                raise ValueError('Groq did not return a research answer.')
            content = message.get('content')
            if (not isinstance(content, str) or not content.strip()
                    or re.search(r'<\s*/?\s*think(?:ing)?\b|<\|(?:channel\|>analysis|analysis\|>)', content, re.I)):
                raise ValueError('Groq returned no usable final answer. No draft accepted.')
            try:
                answer = json.loads(content)
            except (ValueError, TypeError):
                raise ValueError('Groq final text was not valid JSON. No draft accepted.') from None
            if not isinstance(answer, dict):
                raise ValueError('Groq final answer was not a JSON object.')
            self.last_response_metadata = self.redact({
                'model': data.get('model'), 'id': data.get('id'),
                'finish_reason': 'stop', 'usage': data.get('usage')})
            self.last_successful_at = self._wall_clock()
            return self.redact(answer)
