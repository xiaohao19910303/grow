"""Wake the cloud app, trigger its due collection, and verify durable completion."""
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlsplit

BASE = os.getenv('GROW_PUBLIC_URL', '').rstrip('/')
URL = BASE + '/api/reading/scheduled-run'

def validate_target():
    parsed = urlsplit(BASE)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError('Configure GROW_PUBLIC_URL as the HTTPS origin of this installation')


def identity_token():
    url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&' + urlencode({'audience': URL})
    request = urllib.request.Request(url, headers={
        'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)['value']


def wait_for_deploy():
    if os.getenv('GITHUB_EVENT_NAME') != 'push':return
    for _ in range(90):
        try:
            with urllib.request.urlopen(BASE + '/api/health', timeout=90) as response:
                if json.load(response).get('revision') == os.environ['GITHUB_SHA']:return
        except (urllib.error.URLError, TimeoutError):pass
        print('Waiting for the deployment to become healthy', flush=True)
        time.sleep(10)
    raise RuntimeError('The pushed revision did not become healthy')


def main():
    validate_target()
    wait_for_deploy()
    token, refreshed = '', 0
    method = 'POST'
    for attempt in range(60):
        if time.monotonic() - refreshed > 120:
            token, refreshed = identity_token(), time.monotonic()
        request = urllib.request.Request(URL, method=method, headers={
            'Authorization': 'Bearer ' + token, 'X-Copilot-Request': '1'})
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 404):
                raise RuntimeError('Schedule endpoint or credential is not configured') from None
            print('Waiting for the cloud service: HTTP', exc.code, flush=True)
            time.sleep(10)
            continue
        except (urllib.error.URLError, TimeoutError) as exc:
            print('Waiting for the cloud service:', type(exc).__name__, flush=True)
            time.sleep(10)
            continue
        print(json.dumps(result, ensure_ascii=False), flush=True)
        state = result['state']
        if state == 'ready' and result['saved_count'] > 0:
            return
        if state in ('scheduled', 'paused', 'disabled'):
            return
        if state in ('failed', 'cancelled'):
            raise RuntimeError('Daily collection did not finish; inspect the saved job')
        method = 'GET'
        time.sleep(10)
    raise RuntimeError('Timed out waiting for daily reading collection')


if __name__ == '__main__':
    main()
