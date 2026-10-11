"""후보별 사진·감정평가서를 내려받아 모델이 한 번에 볼 수 있는 모음 이미지(contact sheet)로 만든다.

온비드 사진은 GET으로 바로 받아진다(dnldImgFile.do). 감정평가서 PDF도 상세 화면에 박힌 해시로
로그인 없이 받아진다(dnldFile.do). 감정평가서에는 현장사진·위치도·지적도·위성사진이 들어 있어
"그냥 산인지, 관리된 땅인지"를 판단하는 핵심 자료다. 한 감정평가서가 여러 물건(기호1, 기호2…)을
함께 다루는 경우가 있으니 볼 때 주소·기호로 해당 물건을 골라야 한다.
"""
import os
import re
import subprocess
import time
import urllib.request

from PIL import Image, ImageDraw, ImageFont

ORIGIN = "https://www.onbid.co.kr"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
MAX_PHOTOS = 12
MAX_PDF_PAGES = 16          # 사진이 든 쪽만 골라도 너무 많으면 앞쪽부터 이만큼
THUMB_W = 480


def _get(url, path, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": ORIGIN + "/"})
            with urllib.request.urlopen(req, timeout=90) as r, open(path, "wb") as f:
                f.write(r.read())
            return os.path.getsize(path) > 0
        except Exception as e:  # 프록시 터널이 가끔 끊긴다
            if i == tries - 1:
                print(f"  다운로드 실패 {url[:90]}: {e}")
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
    ims = []
    for p in paths:
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        h = int(im.height * width / im.width) if im.width else width
        ims.append(im.resize((width, max(1, h))))
    if not ims:
        return None
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
    sheet.save(out, quality=82)
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


def appraisal(item, d):
    """감정평가서 PDF를 받아 텍스트와 사진이 든 쪽 이미지 모음을 만든다."""
    pdf = item.get("pdf")
    if not pdf or not pdf["name"].lower().endswith(".pdf"):
        return {"status": "없음" if not pdf else f"PDF 아님({pdf['name'].rsplit('.', 1)[-1]})"}
    path = os.path.join(d, "appraisal.pdf")
    url = (f"{ORIGIN}/op/cm/syc/filemng/filemngprcs/FileMngPrcsController/dnldFile.do?"
           f"atchFileLstNo={pdf['atchFileLstNo']}&atchSn={pdf['atchSn']}&hashCrpsNo={pdf['hash']}")
    if not (os.path.exists(path) and os.path.getsize(path) > 1000) and not _get(url, path):
        return {"status": "다운로드 실패"}
    with open(path, "rb") as f:
        if not f.read(5).startswith(b"%PDF"):
            return {"status": "PDF 아님(응답 오류)"}
    txt = os.path.join(d, "appraisal.txt")
    subprocess.run(["pdftotext", "-layout", path, txt], capture_output=True, timeout=180)
    pages = _image_pages(path)
    if 1 not in pages:          # 첫 쪽(감정평가표/요약)은 그림이 없어도 항상 본다
        pages = [1] + pages
    pages = pages[:MAX_PDF_PAGES]
    rendered = []
    for p in pages:
        prefix = os.path.join(d, f"apsl-p{p:02d}")
        subprocess.run(["pdftoppm", "-r", "100", "-png", "-f", str(p), "-l", str(p), "-singlefile", path, prefix],
                       capture_output=True, timeout=180)
        if os.path.exists(prefix + ".png"):
            rendered.append(prefix + ".png")
    sheets = []
    for i in range(0, len(rendered), 8):
        s = contact_sheet(rendered[i:i + 8], os.path.join(d, f"appraisal_sheet{i // 8 + 1}.jpg"), cols=4, width=420,
                          labels=[f"p{int(re.search(r'p(\d+)', os.path.basename(x)).group(1))}" for x in rendered[i:i + 8]])
        if s:
            sheets.append(s)
    has_text = os.path.exists(txt) and len(open(txt, encoding="utf-8", errors="ignore").read().strip()) > 200
    # 스캔본(글자 층 없음)이면 쪽 이미지를 직접 읽어야 한다 — 쪽별 PNG는 100dpi로 남겨 둔다.
    return {"status": "ok", "pdf": path, "text": txt if has_text else None, "scanned": not has_text,
            "pages": pages, "page_images": rendered, "sheets": sheets}


def photos(item, d):
    got = []
    for ph in item.get("photos", [])[:MAX_PHOTOS]:
        p = os.path.join(d, f"photo{int(ph['atchSn']):02d}.jpg")
        url = (f"{ORIGIN}/op/cm/syc/filemng/filemngprcs/FileMngPrcsController/dnldImgFile.do?"
               f"atchFileLstNo={ph['atchFileLstNo']}&atchSn={ph['atchSn']}&thnImgDownloadFlag=false&downloadImageKind=ELGM_FILE_NM")
        if (os.path.exists(p) and os.path.getsize(p) > 0) or _get(url, p):
            got.append(p)
    sheet = contact_sheet(got, os.path.join(d, "photos_sheet.jpg")) if got else None
    return {"count": len(item.get("photos", [])), "downloaded": len(got), "sheet": sheet}


def collect(item, media_root):
    d = os.path.join(media_root, item["mng"])
    os.makedirs(d, exist_ok=True)
    return {"dir": d, "photos": photos(item, d), "appraisal": appraisal(item, d)}
