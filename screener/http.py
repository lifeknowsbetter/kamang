"""stdlib만 사용하는 HTTP 헬퍼. 환경의 프록시 설정을 그대로 따른다."""
import gzip
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# 요청 "시작" 시각을 delay 간격으로 배분한다. 여러 스레드가 동시에 돌아도
# 사이트가 보는 초당 요청 수는 1/delay로 유지된다.
_slot_lock = threading.Lock()
_next_slot = [0.0]


def _throttle(delay):
    if delay <= 0:
        return
    with _slot_lock:
        start = max(time.time(), _next_slot[0])
        _next_slot[0] = start + delay
    wait = start - time.time()
    if wait > 0:
        time.sleep(wait)


def get(url, referer=None, delay=0.35, timeout=40, retries=3):
    """GET 후 본문을 str로 반환. 404/빈 응답은 ''를 돌려준다.

    encar 진단 API는 중복 등록건에 404를 주므로 예외가 아니라 빈 값으로 다룬다.
    """
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(retries):
        _throttle(delay)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return ""
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return ""


def get_json(url, referer=None, **kw):
    body = get(url, referer=referer, **kw)
    if not body.strip():
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def quote(s):
    return urllib.parse.quote(s, safe="")


def map_parallel(fn, items, workers=5):
    """items에 fn을 병렬 적용한다. 순서는 입력 순서를 유지한다.

    요청 간격은 _throttle이 전역으로 관리하므로 workers를 올려도
    사이트가 받는 초당 요청 수는 delay로 결정된다.
    """
    if workers <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
