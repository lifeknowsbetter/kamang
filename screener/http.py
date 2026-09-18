"""stdlib만 사용하는 HTTP 헬퍼. 환경의 프록시 설정을 그대로 따른다."""
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_last_call = [0.0]


def get(url, referer=None, delay=0.35, timeout=40, retries=3):
    """GET 후 본문을 str로 반환. 404/빈 응답은 ''를 돌려준다.

    encar 진단 API는 중복 등록건에 404를 주므로 예외가 아니라 빈 값으로 다룬다.
    """
    headers = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if referer:
        headers["Referer"] = referer
    for attempt in range(retries):
        gap = delay - (time.time() - _last_call[0])
        if gap > 0:
            time.sleep(gap)
        _last_call[0] = time.time()
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
