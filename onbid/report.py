"""리포트 초안(마크다운). 숫자·원문은 모두 채우고, 사진을 봐야 하는 판단만 ⟪…⟫로 남긴다."""
import datetime
import os
import re

from . import config as C

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
        rate = f"{e['rate']}%, " if e.get("rate") not in (None, "", "0", "-") else ""
        low = f"최저 {e['lowest']:,}→" if e.get("lowest") else ""
        return f"{e['date'][5:]} {e['name'][:22]} {low}낙찰 {e['bid']:,}원({rate}{e['bidders']}명, {e['region']})"
    ex = "; ".join(one(e) for e in c["examples"][:3])
    return (f"최근 90일 '{it['comp_key'].split(':', 1)[1]}' 낙찰 {c['n_sold']}건, 낙찰가율 중앙값 {c['median_rate'] or '-'}% — {ex}")


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


def block_A(i, it, today):
    b = it["basis"]
    area = it.get("area") or {}
    nr, be = it.get("next_round"), it.get("budget_entry")
    ratio = it.get("share_ratio")
    L = [f"### {CIRCLED[i]} {it.get('name')} `{seen_tag(it, today)}`",
         f"- 🔗 [온비드 상세]({it['link']})" + ("" if it.get("link_ok") else " (⚠ 링크 확인 실패 — 물건관리번호로 검색)"),
         f"- 물건관리번호 {it['mng']} / 지목 {area.get('use', '-')} / 지분 {area.get('area', '-')} — {area.get('share_note', '')}"
         + (f" (**{ratio * 100:.1f}%**)" if ratio else ""),
         f"- 공고 {it.get('org')} {it.get('branch') or ''} / 의뢰 {it.get('client') or '-'}",
         f"- 감정가 {won(it.get('appraisal'))} → 현재({it.get('round')}회) **{won(it.get('price'))}** "
         f"(감정가의 {pct(it.get('price'), it.get('appraisal'))}, {it.get('fails')} 유찰), 입찰 {dday(it, today)}",
         f"  - 다음 회차: " + (f"{nr['no']}회 {nr['start'][:10]} **{nr['price']:,}원**" if nr else "공고상 미등록(유찰 시 재공고 확인)")
         + f" / 예산 진입: " + (f"{be['no']}회({be['start'][:10]})부터" if be else "미진입"),
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
    L.append("- 📷 사진·도면 판단: ⟪감정평가서 현장사진·지적도·위성사진을 보고: 그냥 산(자연림)인지 / 관리된 땅(정리·경작·포장·건물·도로 이용)인지, 진입로·경사·분묘·경계 표식 등⟫")
    L += _media_lines(it)
    L.append(f"- 종합 리스크: **{it['grade']}**")
    L.append("- 한줄평: ⟪…⟫")
    return "\n".join(L)


def block_B_row(it, today):
    flags = "; ".join(it.get("flags") or [])
    name = (it.get("display") or it.get("name") or "")[:40]
    appr = it.get("appraisal")
    price = it.get("price")
    return (f"| [{name}]({it['link']}) `{seen_tag(it, today)}` | {it['mng']} | {won(price)}" + (f" (감정 {appr:,})" if appr and appr != price else "")
            + f" | {dday(it, today)} | ⟪사진 상태판단⟫ | {it.get('org')} / 보관 {it.get('place', '')[:40]}"
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
         f"- 가격: 감정가 {won(it.get('appraisal'))} → 현재 {won(it.get('price'))} ({it.get('round')}회, 유찰 {it.get('fails')}), 입찰 {dday(it, today)}",
         f"- 보관/인도: {it.get('place')} / 인도책임 {it.get('handover') or '-'} / 공고 {it.get('org')} {it.get('branch') or ''}",
         ]
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


def write_draft(out, data):
    today = datetime.date.fromisoformat(data["today"])
    st = data["stats"]
    sa, sb, sc = st["A"], st["B"], st["C"]
    L = [f"# 📋 온비드 스카우팅 + 권리분석 ({data['today']} 기준) — 초안",
         f"입찰기간 검색창: {data.get('bid_window')}",
         "",
         "> 작성 지침: ⟪…⟫를 사진·감정평가서를 직접 보고 채운다. Track A는 아래 후보 중 상위 5건, Track B는 10건, "
         "Track C는 5건만 최종 리포트에 남긴다. 사진상 문제가 드러난 후보는 빼고 다음 후보로 대체한다. "
         "`🆕`는 처음 본 물건, `↻ MM/DD 보고`는 그날 리포트에 실었던 물건, `검토 MM/DD~`는 후보로만 봤던 물건.",
         "",
         *tracking_section(data.get("tracking")),
         f"## Track A: 지분경매 (조건 충족 {sa['지분물건']}건 → 권역 내 {sa['권역내(수도권·강원·충청)']}건 → "
         f"권역 내 압류재산 {sa['권역내_압류재산']}건, 상세분석 {sa['상세분석']}건)",
         f"재산유형별 {sa['재산유형별']} / 권역 내 압류재산 지목별 {sa['권역내_압류재산_지목별']}",
         ""]
    grades = {}
    for it in data["A"]:
        grades[it["grade"]] = grades.get(it["grade"], 0) + 1
    L.append(f"상세분석 리스크 분포: {grades}")
    L.append("")
    for i, it in enumerate(data["A"][:C.MEDIA_A]):
        L += [block_A(i, it, today), ""]
    L += [f"## Track B: 동산 재판매 (동산 {sb['동산물건']}건 중 키워드 충족 {sb['키워드충족']}건, 상세 {sb['상세분석']}건)",
          f"공고기관별 {sb['공고기관별']}", "",
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
    L += ["", f"## Track C: 자동차 (매각·최저입찰가 {C.CAR_MAX:,}원 이하 {sc['차량']}건, 연료별 {sc['연료별']}, "
          f"경유 2009년식 이전 {sc['경유_2009년이전']}건, 폐차조건부 {sc['폐차조건부']}건, 상세 {sc['상세분석']}건)", ""]
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
