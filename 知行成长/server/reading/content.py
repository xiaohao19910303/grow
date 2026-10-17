"""Bounded public-page retrieval and offline extraction for the on-site reader."""
import asyncio
import io
import ipaddress
import json
import socket

import httpx
from lxml import html
from pypdf import PdfReader
from trafilatura import extract

MAX_BYTES = 8_000_000
MAX_CHARS = 500_000
CONTENT_VERSION = 2


async def public_address(url):
    if url.scheme not in ('http', 'https') or not url.host or url.username or url.password:
        raise ValueError('Invalid article URL')
    if url.port not in (None, 80, 443):
        raise ValueError('Unsupported article port')
    addresses = await asyncio.wait_for(asyncio.to_thread(
        socket.getaddrinfo, url.host, url.port or (443 if url.scheme == 'https' else 80),
        type=socket.SOCK_STREAM), timeout=5)
    ips = list(dict.fromkeys(item[4][0] for item in addresses))
    if not ips or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in ips):
        raise ValueError('Article address must be public')
    return next((ip for ip in ips if ':' not in ip), ips[0])


def extract_content(raw, media_type, url):
    if media_type == 'application/pdf' or raw.startswith(b'%PDF-'):
        pdf = PdfReader(io.BytesIO(raw))
        if pdf.is_encrypted or len(pdf.pages) > 100:
            return None
        parts = []
        size = 0
        for page in pdf.pages:
            text = page.extract_text() or ''
            size += len(text)
            if size > MAX_CHARS:
                return None
            parts.append(text.strip())
        text = '\n\n'.join(parts)
    elif media_type == 'text/plain':
        text = raw.decode('utf-8')
    elif media_type in ('text/html', 'application/xhtml+xml', ''):
        tree = html.fromstring(raw)
        # Respect an explicit publisher paywall; never save its teaser as a full body.
        def restricted(value):
            if isinstance(value, dict):
                if value.get('isAccessibleForFree') in (False, 'false'):
                    return True
                return any(restricted(v) for v in value.values())
            return isinstance(value, list) and any(restricted(v) for v in value)
        for script in tree.xpath('//script[@type="application/ld+json"]/text()'):
            try:
                if restricted(json.loads(script)):
                    return None
            except (ValueError, RecursionError):
                continue
        text = extract(raw, url=url, output_format='markdown', include_comments=False,
                       include_links=False, include_images=False, include_tables=True) or ''
    else:
        return None
    text = text.strip()
    return text if is_readable_text(text) else None


def is_readable_text(text):
    if not isinstance(text,str) or not 100 <= len(text.strip()) <= MAX_CHARS or '\x00' in text:
        return False
    prefix=text.lstrip()[:300].lower()
    return not any(x in prefix for x in ('%pdf-', 'just a moment', 'access denied', 'verify you are human', 'checking your browser'))


async def fetch_article_content(url):
    """No cookies, proxy credentials, model calls or unvalidated redirects."""
    try:
        async with asyncio.timeout(45):
            current = httpx.URL(url)
            # Historical catalogue links use the bare hostname; this publisher's
            # canonical blog is served from www (also our configured RSS host).
            if current.host == 'ruanyifeng.com':
                current = current.copy_with(host='www.ruanyifeng.com')
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=8),
                                         follow_redirects=False, trust_env=False) as client:
                for _ in range(5):
                    address = await public_address(current)
                    # Pin the validated IP for the connection, retaining Host and TLS
                    # verification against the original hostname (no second DNS lookup).
                    target = current.copy_with(host=address)
                    headers = {'Host': current.netloc.decode('ascii'),
                               'User-Agent': 'ZhixingReading/2.0 (personal article reader)'}
                    client.cookies.clear()
                    async with client.stream('GET', target, headers=headers,
                                             extensions={'sni_hostname': current.host}) as response:
                        if response.is_redirect:
                            current = current.join(response.headers['location'])
                            continue
                        response.raise_for_status()
                        if int(response.headers.get('content-length', '0')) > MAX_BYTES:
                            return None
                        chunks = []; size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > MAX_BYTES:
                                return None
                            chunks.append(chunk)
                        media_type = response.headers.get('content-type', '').split(';')[0].lower().strip()
                        return await asyncio.to_thread(extract_content, b''.join(chunks), media_type, str(current))
    except Exception:
        # Source errors must not replace a saved body or leak network details.
        return None
    return None
