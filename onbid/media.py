"""후보별 사진·감정평가서를 내려받아 모델이 한 번에 볼 수 있는 모음 이미지(contact sheet)로 만든다.

온비드 사진은 GET으로 바로 받아진다(dnldImgFile.do). 감정평가서 PDF도 상세 화면에 박힌 해시로
로그인 없이 받아진다(dnldFile.do). 감정평가서에는 현장사진·위치도·지적도·위성사진이 들어 있어
"그냥 산인지, 관리된 땅인지"를 판단하는 핵심 자료다. 한 감정평가서가 여러 물건(기호1, 기호2…)을
함께 다루는 경우가 있으니 볼 때 주소·기호로 해당 물건을 골라야 한다.
"""
import io
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ORIGIN = "https://www.onbid.co.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_PHOTOS = 12
MAX_PDF_PAGES = 16          # 사진이 든 쪽만 골라도 너무 많으면 앞쪽부터 이만큼
THUMB_W = 480


def _is_image(b):
    try:
        Image.open(io.BytesIO(b)).verify()
        return True
    except Exception:
        return False


def _is_pdf(b):
    return b[:5] == b"%PDF-"


_NET_FAILS = 0          # 연결 단계(타임아웃·연결 거부)에서 연속으로 실패한 파일 수 — 온비드 장애 때 media 단계가 몇 시간씩 걸리는 것을 막는다
MAX_NET_FAILS = 6


def _get(url, path, tries=4, validate=None):
    """URL을 받아 path에 쓴다. 응답이 기대한 형식(validate)이 아니면(HTTP 200 오류 페이지 등) 저장하지 않고 재시도한다.
    임시 파일에 쓴 뒤 바꿔 끼워서, 중단돼도 잘린 파일이 남아 다음 실행에서 '받아 둔 것'으로 오인되지 않게 한다."""
    global _NET_FAILS
    if _NET_FAILS >= MAX_NET_FAILS:
        return False
    tmp = path + ".part"
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ORIGIN + "/"})
            with urllib.request.urlopen(req, timeout=90) as r:
                data = r.read()
            if not data or (validate and not validate(data)):
                raise ValueError("응답 본문이 기대한 형식이 아님(오류 페이지?)")
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, path)
            _NET_FAILS = 0
            return True
        except Exception as e:  # 프록시 터널이 가끔 끊긴다
            if i == tries - 1:
                print(f"  다운로드 실패 {url[:90]}: {e}")
                if isinstance(e, OSError) and not isinstance(e, urllib.error.HTTPError):
                    _NET_FAILS += 1
            else:
                time.sleep(2 * (i + 1))
    return False


def _font(size):
    for p in ("/usr/share/fonts/truetype/nanum/NanumGothic.ttf", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                pass
    return ImageFont.load_default()


def contact_sheet(paths, out, cols=4, width=THUMB_W, labels=None):
    ims, kept = [], []
    for k, p in enumerate(paths):
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        if im.width and im.height > im.width * 6:          # 세로로 아주 긴 이미지는 위쪽만(JPEG 한계 65500px)
            im = im.crop((0, 0, im.width, im.width * 6))
        h = int(im.height * width / im.width) if im.width else width
        ims.append(im.resize((width, max(1, h))))
        kept.append(labels[k] if labels else None)
    if not ims:
        return None
    labels = kept if labels else None                      # 못 읽은 이미지가 있어도 라벨이 밀리지 않게
    rows = [ims[i:i + cols] for i in range(0, len(ims), cols)]
    row_h = [max(i.height for i in r) + 22 for r in rows]
    sheet = Image.new("RGB", (cols * width, sum(row_h)), "white")
    draw, font = ImageDraw.Draw(sheet), _font(16)
    y, n = 0, 0
    for r, rh in zip(rows, row_h):
        for c, im in enumerate(r):
            sheet.paste(im, (c * width, y + 22))
            draw.text((c * width + 4, y + 2), labels[n] if labels else f"#{n + 1}", fill="black", font=font)
            n += 1
        y += rh
    try:
        sheet.save(out, quality=82)
    except (OSError, ValueError):
        return None
    return out


def _image_pages(pdf):
    """pdfimages -list로 큰 그림(사진·지도)이 들어 있는 쪽 번호."""
    try:
        out = subprocess.run(["pdfimages", "-list", pdf], capture_output=True, text=True, timeout=120).stdout
    except Exception:
        return []
    pages = []
    for line in out.splitlines()[2:]:
        f = line.split()
        if len(f) > 4 and f[2] == "image" and f[3].isdigit() and int(f[3]) >= 400:
            p = int(f[0])
            if p not in pages:
                pages.append(p)
    return pages


def _pdf_ok(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-" and os.path.getsize(path) > 1000
    except OSError:
        return False


def appraisal(item, d):
    """감정평가서 PDF를 받아 텍스트와 사진이 든 쪽 이미지 모음을 만든다."""
    pdf = item.get("pdf")
    if not pdf or not pdf["name"].lower().endswith(".pdf"):
        return {"status": "없음" if not pdf else f"PDF 아님({pdf['name'].rsplit('.', 1)[-1]})"}
    path = os.path.join(d, "appraisal.pdf")
    url = (f"{ORIGIN}/op/cm/syc/filemng/filemngprcs/FileMngPrcsController/dnldFile.do?"
           f"atchFileLstNo={pdf['atchFileLstNo']}&atchSn={pdf['atchSn']}&hashCrpsNo={pdf['hash']}")
    if not _pdf_ok(path):
        if os.path.exists(path):                # 이전 실행이 남긴 오류 페이지·잘린 파일
            os.remove(path)
        if not _get(url, path, validate=_is_pdf):
            return {"status": "다운로드 실패"}
    txt = os.path.join(d, "appraisal.txt")
    try:
        subprocess.run(["pdftotext", "-layout", path, txt], capture_output=True, timeout=180)
    except (subprocess.TimeoutExpired, OSError):
        return {"status": "글자 변환 실패(시간 초과)"}
    body = open(txt, encoding="utf-8", errors="ignore").read() if os.path.exists(txt) else ""
    pg = body.split("\f")                       # pdftotext는 쪽마다 form feed를 넣는다
    if pg and not pg[-1].strip():
        pg.pop()
    pages = _image_pages(path)
    # 감정평가표(요약) 쪽은 그림이 없어도 항상 본다. 협회 전자서명본은 1쪽이 증명서이고 감정평가표는 3쪽 안팎이다.
    lead = next((i + 1 for i, p in enumerate(pg) if "감정평가표" in p and "전자서명" not in p), 1)
    if lead not in pages:
        pages = [lead] + pages
    pages = pages[:MAX_PDF_PAGES]
    rendered = []
    for p in pages:
        prefix = os.path.join(d, f"apsl-p{p:02d}")
        try:
            subprocess.run(["pdftoppm", "-r", "100", "-png", "-f", str(p), "-l", str(p), "-singlefile", path, prefix],
                           capture_output=True, timeout=180)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if os.path.exists(prefix + ".png"):
            rendered.append(prefix + ".png")
    sheets = []
    for i in range(0, len(rendered), 8):
        labels = ["p" + str(int(re.search(r"p(\d+)", os.path.basename(x)).group(1))) for x in rendered[i:i + 8]]     # f-string 안 역슬래시는 3.12부터라 쓰지 않는다
        s = contact_sheet(rendered[i:i + 8], os.path.join(d, f"appraisal_sheet{i // 8 + 1}.jpg"), cols=4, width=420, labels=labels)
        if s:
            sheets.append(s)
    # 한국감정평가사협회 '전자서명 증명서' 1쪽만 글자 층이 있고 본문은 스캔인 PDF가 있다 — 증명서 쪽은 글자 쪽으로 세지 않는다.
    texty = [p for p in pg if len(re.sub(r"\s", "", p)) >= 80 and "전자서명(원본) 증명서" not in p]
    has_text = bool(texty) and len(texty) * 3 >= len(pg)       # 글자 쪽이 전체의 1/3 이상일 때만 글자 PDF로 본다
    if not rendered and not has_text:
        return {"status": "쪽 이미지 변환 실패(PDF 손상 가능)"}
    # 스캔본(글자 층 없음)이면 쪽 이미지를 직접 읽어야 한다 — 쪽별 PNG는 100dpi로 남겨 둔다.
    return {"status": "ok", "pdf": path, "text": txt if has_text else None, "scanned": not has_text,
            "pages": pages, "page_images": rendered, "sheets": sheets}


def photos(item, d):
    got = []
    for ph in item.get("photos", [])[:MAX_PHOTOS]:
        p = os.path.join(d, f"photo{int(ph['atchSn']):02d}.jpg")
        url = (f"{ORIGIN}/op/cm/syc/filemng/filemngprcs/FileMngPrcsController/dnldImgFile.do?"
               f"atchFileLstNo={ph['atchFileLstNo']}&atchSn={ph['atchSn']}&thnImgDownloadFlag=false&downloadImageKind=ELGM_FILE_NM")
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    cached = _is_image(f.read())
            except OSError:
                cached = False
            if cached:
                got.append(p)
                continue
            os.remove(p)                       # 이전 실행이 남긴 오류 페이지·빈 파일은 지우고 다시 받는다
        if _get(url, p, validate=_is_image):
            got.append(p)
    sheet = contact_sheet(got, os.path.join(d, "photos_sheet.jpg")) if got else None
    return {"count": len(item.get("photos", [])), "downloaded": len(got), "sheet": sheet}


def collect(item, media_root):
    d = os.path.join(media_root, item["mng"])
    os.makedirs(d, exist_ok=True)
    ph = photos(item, d)
    try:
        ap = appraisal(item, d)
    except Exception as e:       # pdftotext/pdftoppm 시간 초과 등 — 이 물건만 감정평가서 없이 진행한다
        ap = {"status": f"처리 실패({type(e).__name__})"}
    return {"dir": d, "photos": ph, "appraisal": ap}
