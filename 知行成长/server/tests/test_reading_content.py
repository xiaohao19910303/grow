"""Article extraction, PDF decoding and public-network boundaries."""
import asyncio
import io
import json
import socket
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from reading.content import extract_content, fetch_article_content, public_address, MAX_BYTES

FIRST='Evidence must be interpreted in context. A careful reader checks the assumptions, compares alternatives and asks what would change a conclusion. '
HTML=('<html><head><meta charset="UTF-8"></head><body><nav>MENU LOGIN ADVERTISEMENT</nav><article><h1>Evidence and decisions</h1>'
      + ''.join(f'<p>Section {i}: {FIRST*4}</p>' for i in range(45))
      + '<p>FINAL SENTENCE. Readers should check both the source and the full argument before deciding.</p></article><footer>FOOTER LINKS</footer><script>EVIL SCRIPT</script></body></html>').encode()

class ContentTests(unittest.IsolatedAsyncioTestCase):
    def test_body_preserves_paragraphs_and_tail_beyond_old_limit(self):
        text=extract_content(HTML,'text/html','https://example.org/story')
        self.assertGreater(len(text),15000);self.assertIn('FINAL SENTENCE',text)
        self.assertGreater(text.count('\n\n'),20)
        for unwanted in ('MENU LOGIN','FOOTER LINKS','EVIL SCRIPT'):self.assertNotIn(unwanted,text)

    def test_rejects_teasers_paywall_challenges_and_binary(self):
        marked=HTML.replace(b'<head>',b'<head><script type="application/ld+json">{"@type":"NewsArticle","isAccessibleForFree":false}</script>')
        self.assertIsNone(extract_content(marked,'text/html','https://example.org'))
        self.assertIsNone(extract_content(b'<p>Short abstract</p>','text/html','https://example.org'))
        self.assertIsNone(extract_content(('Just a moment '+FIRST).encode(),'text/plain','https://example.org'))
        self.assertIsNone(extract_content(HTML,'image/png','https://example.org'))

    def test_pdf_is_decoded_as_text(self):
        writer=PdfWriter();page=writer.add_blank_page(width=612,height=792)
        font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
        stream=DecodedStreamObject();stream.set_data(('BT /F1 12 Tf 30 700 Td ('+FIRST+') Tj ET').encode())
        page[NameObject('/Contents')]=writer._add_object(stream)
        output=io.BytesIO();writer.write(output)
        text=extract_content(output.getvalue(),'application/pdf','https://example.org/article.pdf')
        self.assertIn('Evidence must be interpreted',text);self.assertNotIn('%PDF',text)

    async def test_private_and_mixed_dns_never_connect(self):
        for host in ('127.0.0.1','[::1]','169.254.169.254','10.0.0.1','224.0.0.1','localhost'):
            self.assertIsNone(await fetch_article_content('http://'+host+'/'))
        addresses=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443)),(socket.AF_INET,socket.SOCK_STREAM,6,'',('127.0.0.1',443))]
        with patch('reading.content.socket.getaddrinfo',return_value=addresses):
            with self.assertRaises(ValueError):await public_address(httpx.URL('https://public.example/story'))
        for url in ('file:///etc/passwd','https://user:password@example.org','http://example.org:5432'):
            self.assertIsNone(await fetch_article_content(url))

    async def test_public_ip_pinned_with_host_and_tls_identity(self):
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(200,headers={'content-type':'text/html'},content=HTML)
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch('reading.content.public_address',new=AsyncMock(return_value='93.184.216.34')),patch('reading.content.httpx.AsyncClient',return_value=client):
            text=await fetch_article_content('https://public.example/story')
        self.assertIn('FINAL SENTENCE',text);self.assertEqual(requests[0].url.host,'93.184.216.34')
        self.assertEqual(requests[0].headers['host'],'public.example');self.assertEqual(requests[0].extensions['sni_hostname'],'public.example')

    async def test_redirect_is_validated_before_connect_and_download_is_bounded(self):
        requests=[]
        def respond(request):
            requests.append(request)
            return httpx.Response(302,headers={'location':'http://127.0.0.1/private'})
        original=public_address
        async def resolve(url):
            return '93.184.216.34' if url.host=='public.example' else await original(url)
        client=httpx.AsyncClient(transport=httpx.MockTransport(respond))
        with patch('reading.content.public_address',side_effect=resolve),patch('reading.content.httpx.AsyncClient',return_value=client):
            self.assertIsNone(await fetch_article_content('https://public.example/story'))
        self.assertEqual(len(requests),1)
        client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-length':str(MAX_BYTES+1)},content=b'too big')))
        with patch('reading.content.public_address',new=AsyncMock(return_value='93.184.216.34')),patch('reading.content.httpx.AsyncClient',return_value=client):
            self.assertIsNone(await fetch_article_content('https://public.example/story'))
