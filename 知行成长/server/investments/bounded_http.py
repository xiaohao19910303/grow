"""Pin an approved public DNS result while retaining the original HTTPS TLS name."""
import ipaddress
import socket
from urllib.parse import urlsplit

import httpcore
import httpx
from copilot.core import fail


def public_addresses(url,hosts):
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname not in hosts or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment:
        fail('destination_not_allowed','该公开 HTTPS 目的地尚未由部署者开放。',422)
    try:
        rows=socket.getaddrinfo(parsed.hostname,443,type=socket.SOCK_STREAM)
        addresses=list(dict.fromkeys(row[4][0] for row in rows))
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):raise ValueError()
    except (OSError,ValueError):fail('destination_not_public','目的地无法确认为公开地址，未发起请求。',422)
    return addresses


class PinnedBackend(httpcore.AsyncNetworkBackend):
    def __init__(self,host,addresses,backend=None):
        self.host=host;self.addresses=tuple(addresses);self.backend=backend or httpcore.AnyIOBackend()
    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        if host!=self.host or port!=443:raise httpcore.ConnectError('Destination changed')
        last=None
        for address in self.addresses:
            try:return await self.backend.connect_tcp(address,port,timeout=timeout,local_address=local_address,socket_options=socket_options)
            except (httpcore.ConnectError,httpcore.ConnectTimeout) as error:last=error
        raise last or httpcore.ConnectError('No approved address')
    async def connect_unix_socket(self,*args,**kwargs):raise httpcore.ConnectError('Unix sockets unavailable')
    async def sleep(self,seconds):await self.backend.sleep(seconds)


class ResponseStream(httpx.AsyncByteStream):
    def __init__(self,stream):self.stream=stream
    async def __aiter__(self):
        async for chunk in self.stream:yield chunk
    async def aclose(self):await self.stream.aclose()


class PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self,url,addresses):
        self.pool=httpcore.AsyncConnectionPool(network_backend=PinnedBackend(urlsplit(url).hostname,addresses),max_connections=1,retries=0)
    async def handle_async_request(self,request):
        core_request=httpcore.Request(method=request.method,url=httpcore.URL(scheme=request.url.raw_scheme,host=request.url.raw_host,port=request.url.port,target=request.url.raw_path),
                                      headers=request.headers.raw,content=request.stream,extensions=request.extensions)
        response=await self.pool.handle_async_request(core_request)
        return httpx.Response(response.status,headers=response.headers,stream=ResponseStream(response.stream),extensions=response.extensions)
    async def aclose(self):await self.pool.aclose()
