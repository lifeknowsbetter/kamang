"""리포트 초안(마크다운). 숫자·원문은 모두 채우고, 사진을 봐야 하는 판단만 ⟪…⟫로 남긴다."""
import datetime
import os
import re

from . import config as C
from . import devzone
from . import geo

CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯"


def won(n):
    return f"{n:,}원" if isinstance(n, (int, float)) and n is not None else "-"


def pct(a, b):
    return f"{a / b * 100:.0f}%" if a and b else "-"


def deadline(it):
    m = re.findall(r"\d{4}-\d\d-\d\d \d\d:\d\d", it.get("period") or "")
    if m:
        return m[-1]
    d = (it.get("row") or {}).get("pbctDdlnDt")
    return d


def dday(it, today):
    d = deadline(it)
    if not d:
        return "-"
    n = (datetime.date.fromisoformat(d[:10]) - today).days
    return f"{d[5:10].replace('-', '/')} {d[11:16]} (D-{n})" if n >= 0 else f"{d[:10]} (마감)"


def _media_lines(it):
    m = it.get("media") or {}
    if not m:
        return ["  - (사진 자료 없음)"]
    out = []
    ph = m.get("photos") or {}
    if ph.get("sheet"):
        out.append(f"  - 사진 {ph['downloaded']}/{ph['count']}장: `{ph['sheet']}`")
    else:
        out.append(f"  - 온비드 사진 없음({ph.get('count', 0)}장)")
    ap = m.get("appraisal") or {}
    if ap.get("status") == "ok":
        sheets = ", ".join(f"`{s}`" for s in ap.get("sheets", []))
        out.append(f"  - 감정평가서 사진·도면 쪽 {ap.get('pages')}: {sheets}")
        if ap.get("scanned"):
            out.append(f"  - 감정평가서가 스캔본(글자 없음) → 쪽 이미지 직접 읽기: `{m['dir']}/apsl-pNN.png`")
        elif ap.get("text"):
            out.append(f"  - 감정평가서 본문 텍스트: `{ap['text']}`")
    else:
        out.append(f"  - 감정평가서: {ap.get('status', '없음')}")
    return out


def seen_tag(it, today):
    """매일 돌기 때문에 같은 물건이 반복된다. 처음 보는 물건인지, 전에 리포트에 실었는지 표시."""
    sn = it.get("seen")
    if not sn:
        return "🆕"
    rep = [d for d in sn.get("reported") or [] if d < today.isoformat()]
    if rep:
        return f"↻ {rep[-1][5:].replace('-', '/')} 보고"
    return f"검토 {sn['first_seen'][5:].replace('-', '/')}~"


def tracking_data(st, changed, due_items, queried):
    """지난 후보 결과 요약. changed: 이번 실행에서 결과가 새로 확정되거나 바뀐 물건."""
    items = st["items"]
    rows = []
    for m in changed:
        e = items.get(m, {})
        rows.append({"mng": m, **{k: e.get(k) for k in ("track", "name", "link", "price", "appraisal", "reported")},
                     **(e.get("result") or {})})
    pending = [m for m, e in items.items() if e.get("reported") and not e.get("final")]
    return {"queried": queried, "due": len(due_items), "changed": rows, "pending_reported": len(pending)}


def tracking_section(tr):
    if not tr:
        return []
    L = ["## 🔨 지난 후보 입찰 결과"]
    if not tr.get("queried"):
        L.append("(이번에는 입찰결과를 조회하지 못함)" if tr.get("due") else "(개찰이 지난 추적 물건 없음)")
        return L + [""]
    ch = tr.get("changed") or []
    rep = [r for r in ch if r.get("reported")]
    oth = [r for r in ch if not r.get("reported")]
    if not ch:
        L.append(f"새로 나온 결과 없음 (리포트에 실렸던 물건 중 진행 중 {tr.get('pending_reported', 0)}건)")
    for title, group in (("리포트에 실었던 물건", rep), ("검토만 했던 후보", oth)):
        if not group:
            continue
        L.append(f"**{title}** ({len(group)}건)")
        for r in group:
            st = r.get("status")
            if st in ("낙찰", "낙찰(낙찰후취소)"):
                body = (f"**{st} {won(r.get('bid'))}** (최저가 대비 {r.get('rate') or '-'}%, 감정가 대비 "
                        f"{pct(r.get('bid'), r.get('appraisal'))}, 응찰 {r.get('bidders') or '-'}명)")
            elif st == "유찰":
                body = f"유찰 ({r.get('round')}회, 최저가 {won(r.get('lowest'))}) — 다음 회차로 넘어감"
            else:
                body = st or "-"
            L.append(f"- [{r.get('name')}]({r.get('link')}) {r['mng']} [{r.get('track')}] — {body}, 개찰 {str(r.get('opened'))[:16]}")
    return L + [""]


def comps_line(it):
    c = it.get("comps")
    if not c:
        return None
    if not c["n_sold"]:
        return f"최근 90일 '{it['comp_key'].split(':', 1)[1]}' 낙찰 사례 없음"
    def one(e):
        rate = f"{e['rate']:.0f}%, " if e.get("rate") else ""
        low = f"최저 {e['lowest']:,}→" if e.get("lowest") else ""
        return f"{e['date'][5:]} {e['name'][:22]} {low}낙찰 {e['bid']:,}원({rate}{e['bidders']}명, {e['region']})"
    ex = "; ".join(one(e) for e in c["examples"][:3])
    med = f"낙찰가율 중앙값 {c['median_rate']}%" if c.get("median_rate") else "사례 부족(중앙값 없음)"
    return f"최근 90일 '{it['comp_key'].split(':', 1)[1]}' 비슷한 가격대 낙찰 {c['n_sold']}건, {med} — {ex}"


def place_line(it):
    row = it.get("row") or {}
    d, b = geo.of(row)
    where = row.get("sidoSgkEmd") or "-"
    if d is None:
        return f"- 📍 위치 {where} (산본까지 거리 미상)"
    return f"- 📍 {where} — 산본에서 직선 약 **{d}km** ({b})"


def _tight_notes(it, n=4, width=170):
    notes = it.get("notes") or (it.get("statement") or {}).get("note") or []
    return [f"  > {x[:width]}" for x in notes[:n]] or ["  > (없음)"]


def _sched_table(it):
    sched = it.get("schedule") or []
    if not sched:
        return []
    appr = it.get("appraisal")
    cur = (it.get("round") or "").split("/")[0]
    lines = ["  | 회차 | 입찰 시작 | 공매예정가 | 감정가 대비 | 비고 |", "  |---|---|---|---|---|"]
    passed = True
    for s in sched:
        no = s["no"].split("/")[0]
        if no == cur:
            note, passed = "**이번 회차**", False
        else:
            note = "유찰" if passed else "예정(등록됨)"
        lines.append(f"  | {s['no']} | {s['start'][5:10].replace('-', '/')} | {s['price']:,} | {pct(s['price'], appr)} | {note} |")
    return lines


def appr_lines(it):
    """감정평가서 본문에서 코드가 뽑은 맹지·급경사·접근불가·현황 농지·분묘·제시외 줄. 모델이 사진만 보고 지형을 단정하지 않게 먼저 보여 준다."""
    ex = it.get("appr_excerpt") or []
    ap = (it.get("media") or {}).get("appraisal") or {}
    if ex:
        return ["- 📄 감정평가서 본문 신호(코드가 뽑은 원문 — 판단에 그대로 쓸 것):"] + [f"  > {x}" for x in ex]
    if ap.get("text"):
        return ["- 📄 감정평가서 본문 신호: 맹지·급경사·접근불가·현황 농지·분묘·제시외 문구 없음"]
    return []


def exit_lines(it):
    """KNOWLEDGE 6-A의 예산 상한·출구 상한·손절을 코드가 계산한 값. 리포트에는 이 숫자를 그대로 옮긴다."""
    e = it.get("exit") or {}
    if not e:
        return []
    L = [f"- 🧮 입찰 상한 계산(코드 산출 — 그대로 옮길 것): 예산 상한 **{e['budget_cap']:,}원**"
         " (1,000만 − 등기 실비 5만, ÷1.046)"]
    cap = e.get("exit_cap")
    if cap is not None:
        if cap <= 0:
            L.append("  - 출구 상한: 감정가×0.7에서 실비·목표이익 35만원을 빼면 남는 돈이 없다 → 어떤 가격이든 수익이 나지 않는 구조")
        else:
            L.append(f"  - 출구 상한 **{cap:,}원** (감정가×0.7 − 실비 8만 − 목표이익 30만, ÷1.046. 시세를 모르므로 감정가를 넣은 '위쪽 한계'이고 실제 시세가 낮으면 더 내려간다)")
            fu = e.get("first_under")
            if fu:
                now = (it.get("round") or "").split("/")[0] == fu["no"].split("/")[0]
                L.append(f"  - 출구 상한 이하가 되는 첫 회차: {fu['no']}회 {fu['start'][:10]} {fu['price']:,}원" + (" (이번 회차)" if now else ""))
            else:
                L.append("  - 등록된 회차표에는 출구 상한 이하 회차가 없다")
    loss = e.get("loss")
    if loss is not None:
        L.append(f"  - 못 팔고 지분 매입업체에 감정가의 20%로 넘길 때 현재가 낙찰 시 손실 약 **{loss:,}원**" if loss > 0
                 else "  - 못 팔고 감정가의 20%로 넘겨도 현재가는 회수된다(손실 없음, 단 20%는 미확인 가정)")
    return L


def dev_lines(it):
    """물건 소재지와 가까운 개발 사업(onbid/data/devzones.json). 위치가 가깝다는 사실만 적고 수익으로 읽지 않게 주의 문구를 붙인다."""
    dev = it.get("dev") or []
    if not dev:
        return []
    live = [d for d in dev if d["stage"] != "보류·취소"]
    pool = live or dev
    strong = [d for d in pool if d["tier"] <= 2]
    show = strong[:2] or pool[:1]          # 시군구만 맞는 약한 연관은 한 줄로만 보여 준다
    L = []
    for d in show:
        src = f" · [출처]({d['sources'][0]})" if d.get("sources") else ""
        head = f"- 🏗 개발 연관[{d['why']}]: {d['name']} — {d['stage']}(기준 {d['asof']}, 신뢰 {d['confidence']}) · {d.get('place') or ''}"
        if d["tier"] > 2:
            L.append(head + src)
            continue
        L.append(head + (f" · {d['summary']}" if d.get("summary") else "") + src)
        if d.get("schedule"):
            L.append(f"  - 일정: {d['schedule']}")
        if d.get("land_rules"):
            L.append(f"  - 토지 규제: {d['land_rules']}")
    if any(d["tier"] <= 2 and d["stage"] != "보류·취소" for d in show):
        L.append("  - ⚠ 위치가 가깝다는 사실일 뿐 수익 근거가 아니다. 구역 경계는 지번으로 토지이음·고시 도면에서 확인할 것(읍면동 일치도 구역 밖일 수 있다). "
                 "구역 안이면 지구지정 뒤 취득분은 개발이익이 배제된 보상가가 기준일 수 있고, 토지거래허가구역이면 압류재산 공매 낙찰은 허가 면제로 읽히나(시행령 제11조제3항제12호) 되팔 때 매수인에게 허가가 필요할 수 있다.")
    return L


def devscan_section(ds):
    """전체 압류 부동산 목록(상세 열기 전)에서 개발 사업과 연관된 물건. 상위 목록에 못 든 물건도 한눈에 보여 준다."""
    if not ds:
        return []
    if not ds.get("entries"):
        return ["## 🏗 개발 사업 연관 물건", "개발 사업 데이터(onbid/data/devzones.json)를 읽지 못해 이번에는 연관 표시를 생략한다.", ""]
    c = ds["counts"]
    L = ["## 🏗 개발 사업 연관 물건 — 전국 압류 부동산 전체 목록 기준",
         f"압류재산 {ds['total']}건 중 개발 사업과 위치가 맞는 물건 {ds['hits']}건(읍면동 일치 {c['1']}건, 같은 시·구·읍면동 미특정 {c['2']}건, 그 밖에 시군구만 맞는 약한 연관 {c['3']}건). "
         f"데이터 {ds['entries']}개 사업, 기준 {ds.get('built') or '-'}. "
         "상세(권리·점유·사진)를 열기 전의 1차 목록이라 위험은 따로 확인해야 하고, 위치가 가깝다는 사실일 뿐 수익을 뜻하지 않는다.",
         "",
         "| 물건 | 최저가(감정가 대비) | 산본 | 연관 사업 | 단계 | 연관 |", "|---|---|---|---|---|---|"]
    for h in ds["shown"]:
        appr, pr = h.get("appraisal"), h.get("price")
        d = h["dev"]
        nm = (h.get("name") or "")[:34]
        L.append(f"| [{nm}]({h['link']}) {'(지분)' if h.get('share') else ''} {h.get('cat') or ''} | {won(pr)}" + (f" ({pct(pr, appr)})" if appr and pr else "")
                 + f" | {h['dist']}km | {d['name'][:30]} | {d['stage']} | {d['why']} |")
    L.append("")
    return L


def block_A(i, it, today):
    b = it["basis"]
    area = it.get("area") or {}
    nr, be = it.get("next_round"), it.get("budget_entry")
    ratio = it.get("share_ratio")
    L = [f"### {CIRCLED[i]} {it.get('name')} `{seen_tag(it, today)}`",
         f"- 🔗 [온비드 상세]({it['link']})" + ("" if it.get("link_ok") else " (⚠ 링크 확인 실패 — 물건관리번호로 검색)"),
         f"- 물건관리번호 {it['mng']} / 지목 {area.get('use', '-')} / 지분 {area.get('area', '-')} — {area.get('share_note', '')}"
         + (f" (**{ratio * 100:.1f}%**)" if ratio else ""),
         place_line(it),
         *dev_lines(it),
         f"- 공고 {it.get('org')} {it.get('branch') or ''} / 의뢰 {it.get('client') or '-'}",
         f"- 감정가 {won(it.get('appraisal'))} → 현재({it.get('round')}회) **{won(it.get('price'))}** "
         f"(감정가의 {pct(it.get('price'), it.get('appraisal'))}, {it.get('fails')} 유찰), 입찰 {dday(it, today)}",
         f"  - 다음 회차: " + (f"{nr['no']}회 {nr['start'][:10]} **{nr['price']:,}원**" if nr else "공고상 미등록(유찰 시 재공고 확인)"),
         *_sched_table(it),
         f"- 농지여부: " + ("⚠농지취득자격증명 필요" if it["land_class"] == "농지" else f"해당 없음({area.get('use', '')})"),
         ]
    if b["공유자수"]:
        L.append(f"- ⚠공유자 현황: {b['공유자수']}명(법인 {b['공유자_법인']}), 등록일 {', '.join(b['공유자_등록일'])}"
                 f" → ⚠공유자 우선매수신청 리스크" + (" / 장기 방치 지분 가능성(10년↑)" if b["공유자_장기"] else ""))
    elif b.get("정보부족"):
        L.append("- 공유자 현황: 등기 주요정보 0건 제공 — 지분물건이므로 공유자 존재 확실, 확인 불가")
    else:
        L.append("- 공유자 현황: 등기 주요정보상 공유자 행 없음")
    if b["기타등기권리"]:
        L.append(f"  - 기타 등기 권리: {', '.join(b['기타등기권리'])}")
    if not b["명세서공개"]:
        L.append("- 인수권리: 공매재산명세서 비공개 — 입찰 임박 시 재확인 필요")
    elif b["인수권리"] or b["지상권개요"]:
        L.append(f"- ⚠매수인 인수 위험: {' / '.join(b['인수권리'] + b['지상권개요'])}")
    else:
        L.append(f"- 인수권리: 명세서(기준일 {it['statement'].get('base_date')}) 공란 — 권리관계 깨끗함")
    if b["점유"] or b["임대차"] or b["명세서점유행"] or b["명세서임차행"]:
        L.append(f"- ⚠점유자: 점유 {b['점유']}건·임대차 {b['임대차']}건 {b['명세서점유행'][:8]} → ⚠명도 책임 발생 가능")
    else:
        L.append("- 점유자: 없음(점유·임대차 0건, 명세서 공란)")
    notes = it.get("notes") or (it.get("statement") or {}).get("note") or []
    L.append("- 유의사항 원문:")
    L += [f"  > {n}" for n in notes] or ["  > (없음)"]
    if it.get("favor_flags"):
        L.append(f"  - 플래그: {', '.join(it['favor_flags'])} → 지분 되팔기 전략에 유리한 신호")
    kv = it.get("kv", {})
    L.append(f"- 감정평가서 요약: 이용상태 「{kv.get('이용상태', '-')}」 / 주위 「{kv.get('위치 및 주위환경', '-')[:120]}」"
             + (" → 자연림 기재(그냥 산일 가능성)" if it.get("natural_hint") else ""))
    L += appr_lines(it)
    if any("현황은 전·답" in m or "현황은 전" in m for _, m in it.get("appr_flags") or []):
        L.append("- ⚠ 지목은 농지가 아니지만 감정평가서상 현황이 전·답(경작 중) — 농지법은 지목과 무관하게 실제 경작지를 농지로 보므로 농지취득자격증명이 필요할 수 있다. 관할 읍·면·동에 확인 전에는 위험 높음")
    if it.get("bad_exit"):
        L.append("- ⛔ 맹지·분묘가 감정평가서나 유의사항에 나온다. 위 원문 줄로 실제 맹지·분묘 딸린 지분인지 확인하고, 맞으면 되팔 상대가 거의 없으니 **입찰을 권하지 않는다**(KNOWLEDGE 6-A 6항: 맹지 단독 소유도 감정가 30%가 한도)")
    L += exit_lines(it)
    L.append("- 📷 사진·도면 판단: ⟪감정평가서 현장사진·지적도·위성사진을 보고: 그냥 산(자연림)인지 / 관리된 땅(정리·경작·포장·건물·도로 이용)인지, 진입로·경사·분묘·경계 표식 등⟫")
    L += _media_lines(it)
    L.append(f"- 종합 리스크: **{it['grade']}**")
    L.append("- 한줄평: ⟪…⟫")
    return "\n".join(L)


def _km_tag(it):
    d, _ = geo.of(it.get("row") or {})
    return f"산본 {d}km · " if d is not None else ""


def block_B_row(it, today):
    flags = "; ".join(it.get("flags") or [])
    name = (it.get("display") or it.get("name") or "")[:40]
    appr = it.get("appraisal")
    price = it.get("price")
    return (f"| [{name}]({it['link']}) `{seen_tag(it, today)}` | {it['mng']} | {won(price)}" + (f" (감정 {appr:,})" if appr and appr != price else "")
            + f" | {dday(it, today)} | ⟪사진 상태판단⟫ | {_km_tag(it)}{it.get('org')} / 보관 {it.get('place', '')[:40]}"
            + (f"; {flags}" if flags else "") + " |")


def block_C(i, it, today):
    s = it["subsidy"]
    kv = it.get("kv", {})
    cc = f"{it['cc']:,}cc" if it.get("cc") else "배기량 미상"
    km = f"{it['km']:,}km" if it.get("km") else "주행거리 미상"
    L = [f"### {CIRCLED[i]} {it.get('name')} `{seen_tag(it, today)}`",
         f"- 🔗 [온비드 상세]({it['link']})" + ("" if it.get("link_ok") else " (⚠ 링크 확인 실패)"),
         f"- 물건관리번호 {it['mng']} / {kv.get('제조사', '')} {kv.get('모델명') or kv.get('차종', '')} / {it.get('year')}년식 / "
         f"{it.get('fuel')} / {cc} / {km} / 차량번호 {it.get('plate') or '-'}",
         place_line(it),
         f"- 가격: 감정가 {won(it.get('appraisal'))} → 현재 {won(it.get('price'))} ({it.get('round')}회, 유찰 {it.get('fails')}), 입찰 {dday(it, today)}",
         f"- 보관/인도: {it.get('place')} / 인도책임 {it.get('handover') or '-'} / 공고 {it.get('org')} {it.get('branch') or ''}",
         ]
    a = it.get("assess")
    if a:
        r3 = lambda x: int(round(x, -3))
        L.append(f"- 💰 본전 시세: 예상 낙찰가 {won(r3(a['clear']))}(최저가 구간 낙찰가율 중앙값) + 취득세·탁송·상품화·예비비 {won(r3(a['extra']))} "
                 f"= **{won(int(round(a['breakeven'], -4)))} 이상에 팔려야 본전**(낙찰가 대비 +{a['need_pct']:.0f}%). 엔카·헤이딜러 시세와 비교 ⟪시세 확인 결과⟫")
    if it.get("flags"):
        L.append(f"- ⚠ {', '.join(it['flags'])}")
    L.append(f"- 조기폐차 지원금: 등급 {s.get('grade_est')} / 대상 {s.get('eligible')}"
             + (f" / 예상 {won(s.get('amount_lo'))}~{won(s.get('amount_hi'))}" if s.get("amount_hi") else ""))
    for c in s.get("caveats", []):
        L.append(f"  - {c}")
    if s.get("basis"):
        L.append(f"  - 근거: {s['basis']}")
    notes = it.get("notes") or []
    if notes:
        L.append("- 유의사항 원문:")
        L += [f"  > {n}" for n in notes]
    cl = comps_line(it)
    if cl:
        L.append(f"- 📈 동종 낙찰: {cl}")
    L.append("- 📷 사진·감정평가표 판단: ⟪외관·실내·계기판(경고등/주행거리)·엔진룸·하부 부식, 감정평가표 체크(시동/작동), 사고이력 → 작동 가능성⟫")
    L += _media_lines(it)
    L.append("- 한줄평: ⟪…⟫")
    return "\n".join(L)


def block_D(i, it, today):
    area = it.get("area") or {}
    nr = it.get("next_round")
    icon = {"R": "🔴", "Y": "🟡", "G": "🟢"}
    L = [f"### {CIRCLED[i]} {it.get('name')} `{seen_tag(it, today)}`",
         f"- 🔗 [온비드 상세]({it['link']})" + ("" if it.get("link_ok") else " (⚠ 링크 확인 실패 — 물건관리번호로 검색)"),
         f"- 물건관리번호 {it['mng']} / {(it.get('row') or {}).get('ctgrFullNm', '-')} / 면적 {area.get('area', '-')} {area.get('share_note', '') or ''}"
         + (f" / 같은 건물·가격 호실 {it['dup']}개 더 있음" if it.get("dup") else ""),
         place_line(it),
         *dev_lines(it),
         f"- 공고 {it.get('org')} {it.get('branch') or ''}",
         f"- 감정가 {won(it.get('appraisal'))} → 현재({it.get('round')}회) **{won(it.get('price'))}** "
         f"(감정가의 {pct(it.get('price'), it.get('appraisal'))}, {it.get('fails')} 유찰), 입찰 {dday(it, today)}",
         f"  - 다음 회차: " + (f"{nr['no']}회 {nr['start'][:10]} **{nr['price']:,}원**" if nr else "공고상 미등록(유찰 시 재공고 확인)"),
         *_sched_table(it)]
    if it.get("ratio") is not None and it["ratio"] <= 15:
        if it.get("land_class") == "건물":
            L.append(f"- ⚠ 최저가가 감정가의 {it['ratio']}%({it.get('fails')} 유찰): 감정이 오래됐거나 **인수해야 할 돈(임차보증금·체납관리비)·점유 문제**가 값에 반영된 경우가 많다. 낙찰가가 아니라 총부담으로 비교할 것")
        else:
            L.append(f"- ⚠ 최저가가 감정가의 {it['ratio']}%({it.get('fails')} 유찰): 회차마다 기계적으로 내려온 값이다. 안 팔린 이유(맹지·진입로·분묘·경사·경계)를 먼저 확인할 것")
    if it.get("deposit_sum"):
        L.append(f"- ⚠ 총부담 최대치(대항력 임차인 보증금을 전부 인수하는 최악의 경우): {won((it.get('price') or 0) + it['deposit_sum'])} "
                 f"(최저가 {won(it.get('price'))} + 보증금 {won(it['deposit_sum'])})")
    L.append("- 위험 신호: " + (" / ".join(f"{icon[s]} {m}" for s, m in it.get("risk_flags", [])) or "🟢 유의사항·명세서에 위험 문구 없음(안전하다는 뜻은 아님)"))
    L.append("- 유의사항 원문:")
    L += _tight_notes(it)
    kv = it.get("kv", {})
    L.append(f"- 감정평가서 요약: 이용상태 「{kv.get('이용상태', '-')[:80]}」 / 주위 「{kv.get('위치 및 주위환경', '-')[:100]}」")
    L += appr_lines(it)
    L.append("- 📷 사진·도면 판단: ⟪감정평가서·온비드 사진을 보고: 실제 쓰이는 땅/건물인지, 출입·경계·점유 흔적, 공실 여부⟫")
    L += _media_lines(it)
    L.append("- 💰 출구: ⟪되팔 상대(이웃 땅 주인·공유자·세입자 등)와 근거 시세, 건물이면 같은 동네 월세 1~2건(WebSearch) 확인 결과. 근거가 없으면 '시세 확인 필요'⟫")
    L.append(f"- 종합 리스크: **{it['grade']}**")
    L.append("- 한줄평: ⟪…⟫")
    return "\n".join(L)


def write_draft(out, data):
    today = datetime.date.fromisoformat(data["today"])
    st = data["stats"]
    sa, sb, sc, sd = st["A"], st["B"], st["C"], st["D"]
    L = [f"# 📋 온비드 스카우팅 + 권리분석 ({data['today']} 기준) — 초안",
         f"입찰기간 검색창: {data.get('bid_window')} · 기준 위치: {C.HOME}(직선거리 대략, 가까운 순으로 정렬)",
         "",
         "> 작성 지침: ⟪…⟫를 사진·감정평가서를 직접 보고 채운다. Track A는 아래 후보 중 상위 5건, Track D는 5건, Track B는 10건, "
         "Track C는 5건만 최종 리포트에 남긴다. 사진상 문제가 드러난 후보는 빼고 다음 후보로 대체한다. "
         "`🆕`는 처음 본 물건, `↻ MM/DD 보고`는 그날 리포트에 실었던 물건, `검토 MM/DD~`는 후보로만 봤던 물건. "
         "최저입찰가 1,000만원 이하 전국이며, 어느 것도 수익이 보장된 물건이 아니다.",
         "",
         *tracking_section(data.get("tracking")),
         f"## Track A: 지분 부동산 (부동산 {sa['부동산물건']}건 중 지분 {sa['지분물건']}건 → 압류재산 {sa['압류재산_지분']}건"
         f"(산본 {C.NEAR_KM}km 이내 {sa['산본_50km_이내']}건), 상세분석 {sa['상세분석']}건)",
         f"재산유형별 {sa['재산유형별']} / 지목별 {sa['지목별']}",
         ""]
    grades = {}
    for it in data["A"]:
        grades[it["grade"]] = grades.get(it["grade"], 0) + 1
    L.append(f"상세분석 리스크 분포: {grades}")
    L.append("")
    for i, it in enumerate(data["A"][:C.MEDIA_A]):
        L += [block_A(i, it, today), ""]
    L += [f"## Track D: 단독 소액 부동산 — 지분이 아닌 토지·건물 호실 (단독·미표시 {sd['단독·미표시']}건 → 압류재산 {sd['압류재산']}건"
          f"(산본 {C.NEAR_KM}km 이내 {sd['산본_50km_이내']}건), 유형 {sd['유형별']}, 상세분석 {sd['상세분석']}건)",
          "싼 건물 호실은 임차인·전입세대·인수권리·체납관리비 때문에 싼 경우가 많다. 🔴가 있으면 총부담을 다시 계산한다.", ""]
    grades = {}
    for it in data["D"]:
        grades[it["grade"]] = grades.get(it["grade"], 0) + 1
    L.append(f"상세분석 리스크 분포: {grades}")
    L.append("")
    for i, it in enumerate(data["D"][:C.MEDIA_D]):
        L += [block_D(i, it, today), ""]
    L += devscan_section(data.get("devscan"))
    L += [f"## Track B: 동산 재판매 (동산 {sb['동산물건']}건 중 후보 {sb['후보']}건(산본 {C.NEAR_KM}km 이내 {sb['산본_50km_이내']}건), 상세 {sb['상세분석']}건)",
          f"제외한 권리형·폐기물 등 {sb['권리형·폐기물 등 제외']}", f"공고기관별 {sb['공고기관별']}", "",
          "| 물건명 | 물건관리번호 | 최저입찰가 | 마감일(D-n) | 📷 상태판단 | 주의사항 |", "|---|---|---|---|---|---|"]
    for it in data["B"][:C.MEDIA_B]:
        L.append(block_B_row(it, today))
    L += ["", "Track B 후보별 사진 자료·동종 낙찰:"]
    for it in data["B"][:C.MEDIA_B]:
        L.append(f"- {it['mng']} {(it.get('display') or it.get('name') or '')[:30]}")
        cl = comps_line(it)
        if cl:
            L.append(f"  - 📈 {cl}")
        L += _media_lines(it)
    L += ["", f"## Track C: 자동차 (최저입찰가 {C.CAR_MAX:,}원 이하 {sc['차량']}건 중 실효 없음 {sum(sc['실효없음_제외'].values())}건 제외 → 남은 {sc['남은_차량']}건, 상세 {sc['상세분석']}건)",
          f"제외 이유별 {sc['실효없음_제외']} — 낙찰가가 시세에 붙거나 되팔 상대·운반이 막힌 물건이다(onbid/carfilter.py).",
          f"연료별 {sc['연료별']} / 경유 2009년식 이전 {sc['경유_2009년이전']}건 / 폐차조건부 {sc['폐차조건부']}건", ""]
    for i, it in enumerate(data["C"][:C.MEDIA_C]):
        L += [block_C(i, it, today), ""]
    md = data.get("missing_details") or {}
    if any(md.values()):
        L.append(f"(상세 수집 실패: {md})")
    L += ["", C.FOOTER]
    with open(os.path.join(out, "report_draft.md"), "w") as f:
        f.write("\n".join(L) + "\n")


def write_failure(out, today, reason):
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, "report_draft.md"), "w") as f:
        f.write(f"# 📋 온비드 주간 스카우팅 + 권리분석 ({today.isoformat()} 기준)\n\n"
                f"**Track A: 지분경매** — 이번 주는 실시간 데이터 수집 실패 ({reason})\n\n"
                f"**Track B: 동산 재판매** — 이번 주는 실시간 데이터 수집 실패\n\n"
                f"**Track C: 자동차** — 이번 주는 실시간 데이터 수집 실패\n\n{C.FOOTER}\n")
