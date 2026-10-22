"""Provider-reported numeric usage only. Missing usage is never zero or an estimate."""
import json
import re

MAX_COUNT = 2**53 - 1
FIELDS = ('input_tokens', 'output_tokens', 'cache_read_input_tokens',
          'cache_creation_input_tokens', 'reasoning_output_tokens', 'total_tokens')
MODEL = re.compile(r'(?:claude-|gpt-|codex-)[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,95}\Z')


def counters(value, mapping=None):
    if type(value) is not dict:
        return {}
    return {target: value[key] for key, target in (mapping or {k:k for k in FIELDS}).items()
            if type(value.get(key)) is int and 0 <= value[key] <= MAX_COUNT}


def safe_usage(value):
    """Rebuild an allowlisted shape; never persist provider prose or arbitrary keys."""
    if type(value) is not dict or value.get('source') not in ('CLAUDE_RESULT', 'CODEX_CLI', 'CODEX_APP_SERVER'):
        return None
    metrics = counters(value.get('metrics'))
    models = []
    for item in value.get('models', []) if type(value.get('models')) is list else []:
        if type(item) is dict and type(item.get('model')) is str and MODEL.fullmatch(item['model']):
            models.append({'model': item['model'], 'metrics': counters(item.get('metrics'))})
    models = models[:20]
    scope = value.get('scope') if value.get('scope') in ('CALL', 'THREAD_CUMULATIVE') else 'CALL'
    return dict(schema=1, source=value['source'], scope=scope, estimated=False,
                status='REPORTED' if metrics else 'MODEL_ONLY' if any(x['metrics'] for x in models) else 'UNAVAILABLE',
                metrics=metrics, models=models)


def claude_usage(obj):
    obj = obj if type(obj) is dict else {}
    models = []
    mapping = {'inputTokens':'input_tokens', 'outputTokens':'output_tokens',
               'cacheReadInputTokens':'cache_read_input_tokens',
               'cacheCreationInputTokens':'cache_creation_input_tokens'}
    for name, value in obj.get('modelUsage', {}).items() if type(obj.get('modelUsage')) is dict else []:
        if type(name) is str and MODEL.fullmatch(name):
            models.append(dict(model=name, metrics=counters(value, mapping)))
    return safe_usage(dict(source='CLAUDE_RESULT', metrics=counters(obj.get('usage')), models=models))


def codex_usage(events):
    mapping = {'input_tokens':'input_tokens', 'output_tokens':'output_tokens',
               'cached_input_tokens':'cache_read_input_tokens',
               'reasoning_output_tokens':'reasoning_output_tokens', 'total_tokens':'total_tokens'}
    metrics = {}
    for event in events:
        if type(event) is dict and event.get('type') == 'turn.completed':
            for key, value in counters(event.get('usage'), mapping).items():
                metrics[key] = metrics.get(key, 0) + value
    return safe_usage(dict(source='CODEX_CLI', metrics=metrics))


def from_output(engine, raw):
    """Inspect only native usage fields; agent text and reasoning are never decoded further."""
    try:
        if engine == 'claude':
            return claude_usage(json.loads(raw))
        events = []
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except (ValueError, TypeError):
                continue
            if type(event) is dict and event.get('type') == 'turn.completed':
                events.append(event)
        return codex_usage(events)
    except (ValueError, TypeError):
        return safe_usage(dict(source='CLAUDE_RESULT' if engine == 'claude' else 'CODEX_CLI'))


def app_server_usage(params):
    usage = params.get('tokenUsage', {}) if type(params) is dict else {}
    mapping = {'inputTokens':'input_tokens', 'outputTokens':'output_tokens',
               'cachedInputTokens':'cache_read_input_tokens',
               'cacheWriteInputTokens':'cache_creation_input_tokens',
               'reasoningOutputTokens':'reasoning_output_tokens', 'totalTokens':'total_tokens'}
    return safe_usage(dict(source='CODEX_APP_SERVER', scope='THREAD_CUMULATIVE',
                           metrics=counters(usage.get('total') if type(usage) is dict else None, mapping)))
