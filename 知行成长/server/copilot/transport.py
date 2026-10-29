"""OpenAI-compatible SSE transport; no retries, secrets or raw errors logged."""
import asyncio
import json
from urllib.parse import urlparse


async def qwen_stream(messages, config):
    import httpx
    url = urlparse(config['url'])
    if url.scheme not in ('https', 'http') or not url.hostname:
        raise ValueError('Model endpoint must be a valid URL')
    payload = {'model': config['model'], 'messages': messages, 'stream': True}
    stopped = False
    options={'transport':config['_transport'],'trust_env':False} if config.get('_transport') is not None else {}
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15), follow_redirects=False,**options) as client:
        async with client.stream('POST', config['url'], json=payload,
                                 headers={'Authorization': 'Bearer ' + config['key']}) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if len(line) > 200000:
                    raise ValueError('Oversized event')
                if not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    if not stopped:
                        raise ValueError('Incomplete completion')
                    yield {'done': True}
                    return
                packet = json.loads(data)
                if packet.get('error'):
                    raise ValueError(f"Provider error: {packet['error']}")
                if packet.get('usage') is not None:
                    yield {'usage': packet['usage']}
                for choice in packet.get('choices', []):
                    reason = choice.get('finish_reason')
                    if reason and reason != 'stop':
                        raise ValueError('Truncated or rejected completion')
                    if reason == 'stop':
                        stopped = True
                    chunk = choice.get('delta', {}).get('content')
                    if chunk:
                        yield {'text': chunk}
    raise ValueError('Missing end of stream')
