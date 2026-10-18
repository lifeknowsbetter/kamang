# 온비드 스카우팅

온비드(www.onbid.co.kr) **압류재산 공매** 스카우팅 파이프라인이다. 평일 저녁 루틴이 최저입찰가 1,000만원 이하의 부동산·동산·자동차를
전국에서 모아 권리분석·사진판단 리포트를 만들고, 지난 후보의 낙찰 결과와 같은 종류 물건의 최근 낙찰 사례를 붙인다.
법원경매(courtauction.go.kr)와 등기부 실시간조회(iros.go.kr)는 쓰지 않는다. 등기 정보는 온비드 물건상세의
"등기사항증명서 주요정보"(공개)만 쓴다.

## 리포트의 성격

- **사용자 조건**: 성인 1인, 군포시 산본동 거주, 자차 없음, 온비드 전자입찰로 집에서 처리, 소송 없이 협상·재매각만.
- **필터이지 수익 목록이 아니다.** 1,000만원 이하 공매는 낙찰가가 시세로 올라가고 고정비(취득세·탁송·수리·시간)가 커서
  본전이 기본값이다. 리포트는 구조적으로 갭이 있는 소수만 남기고 실효 없는 물건을 걸러 준다. "수익 보장"은 쓰지 않는다.
- **전국, 산본 근접 우선.** 지역을 자르지 않고 산본에서 직선거리가 가까운 물건부터 보여준다(`onbid/geo.py`).
- **자동차 실효 필터.** 낙찰가가 시세에 붙거나 되팔 상대·운반이 막힌 차량은 뺀다(`onbid/carfilter.py`).
- **권리형 자산 제외.** 공제조합 출자증권·비상장주식·회원권·특허 등은 되팔 상대가 좁아 동산 후보에서 뺀다(`config.MVAST_RIGHTS` 등).
- **개발 사업 연관 표시.** 부동산 물건이 반도체·공공택지·산업단지·교통 등 개발 사업과 위치가 가까운지 사실로만 보여준다
  (`onbid/devzone.py`, 데이터는 `onbid/data/devzones.json`). 위치가 가깝다는 뜻일 뿐 수익 근거가 아니다.

트랙 구성과 판정 규칙은 [`onbid/README.md`](onbid/README.md)에 있다.

## 빠른 시작

Node(Playwright + Chromium), Python 3(Pillow), poppler-utils가 필요하다. 클라우드 세션 이미지에는 모두 들어 있다.

```bash
python3 -m onbid.run --out out/onbid                 # 검색→상세→사진·감정평가서→초안
python3 -m onbid.run --out out/onbid --skip-search   # 검색 결과 재사용
python3 -m onbid.track mark out/onbid <물건관리번호>...  # 오늘 리포트에 실은 물건 표시
python3 -m onbid.track show                          # 추적 현황
python3 -m onbid.devzone validate                    # 개발 사업 데이터 검사
```

산출물은 `out/onbid/report_draft.md`(초안), `candidates.json`, `media/`(사진·감정평가서 모음)이다. 자세한 내용은 `onbid/README.md`.

## 루틴

브랜치 `claude/onbid-weekly-scouting-b8yrsl`의 지시문 파일이 루틴의 정식 지시문이다. 트리거에는 짧은 프롬프트만 저장하고
"저장소를 클론해 지시문을 따르라"고 적어 둔다. 절차를 바꿀 때는 이 저장소의 파일만 고치면 다음 실행부터 반영된다.

| 루틴 | 시각(KST) | 정식 지시문 | 하는 일 |
|---|---|---|---|
| 스크리닝 `trig_019hZUt3uvmwRpA1jKV8zsaN` | 평일 18:48 | `onbid/ROUTINE_PROMPT.md` | 파이프라인 실행 → 사진 판단 → 리포트 → 실은 물건 표시·상태 커밋 |
| 공부 `trig_01LyZ9EMR2KHo3CS2uARHhgq` | 매일 16:52 | `onbid/LEARN_PROMPT.md` | 주제 하나 웹 조사 → 노트 갱신·커밋(일요일은 개발 데이터 점검) |

**저장소 연결**: 루틴 세션이 push하려면 claude.ai 루틴 편집 화면의 "리포지토리"에 `lifeknowsbetter/kamang`이 연결돼 있어야 한다
(2026-10-18 사용자가 연결). 연결이 없으면 클론(공개 저장소)은 되지만 push가 403으로 막히고, 루틴 세션에는 저장소를 붙이는 도구가 없다.

## 문서 지도

| 파일 | 내용 |
|---|---|
| `README.md` | 이 문서. 저장소 개요와 문서 지도 |
| [`onbid/README.md`](onbid/README.md) | 트랙·실행·루틴·단계, 온비드 동작에서 확인한 사실, 판정 규칙 |
| [`onbid/ROUTINE_PROMPT.md`](onbid/ROUTINE_PROMPT.md) | 평일 저녁 스크리닝 루틴의 정식 지시문(작성 규칙·리포트 형식) |
| [`onbid/LEARN_PROMPT.md`](onbid/LEARN_PROMPT.md) | 매일 공부 루틴의 정식 지시문(주제 선정·기록·저장, 일요일 개발 데이터 점검) |
| [`onbid/knowledge/KNOWLEDGE.md`](onbid/knowledge/KNOWLEDGE.md) | 공부로 쌓은 지식 노트(패턴·함정·비용·실전 수치·입찰가 규칙·주제 큐) |
| `onbid/knowledge/journal/` | 날짜별 공부 일지(`YYYY-MM-DD.md`) |
| [`onbid/data/README.md`](onbid/data/README.md) | `devzones.json`(개발 사업 목록) 사양과 갱신 절차 |
| `onbid/state/tracked.json` | 추적 상태(검토·추천 물건과 낙찰 결과). 루틴이 커밋한다 |

## 디렉터리

```
onbid/
  run.py        실행기(검색→상세→파싱→사진→추적→초안)
  analyze.py    1차 선별, 등급·위험 신호, 감정평가서 신호, 출구 숫자 계산
  carfilter.py  자동차 실효 필터와 본전 시세 계산
  geo.py        산본 기준 직선거리·구간
  devzone.py    개발 사업 연관 매칭·집계·검증
  parse.py      상세 화면·명세서 파싱
  media.py      사진·감정평가서 PDF 수집, 모음 이미지
  track.py      추적 상태, 낙찰 결과, 동종 낙찰 사례
  report.py     리포트 초안 작성
  subsidy.py    조기폐차 지원금 추정
  config.py     조건·상수(판정 기준은 여기서 바꾼다)
  js/           Playwright 수집기(search, details, results, lib)
  data/         개발 사업 데이터(devzones.json)와 사양서
  knowledge/    지식 노트와 journal/
  state/        추적 상태(tracked.json)
  ROUTINE_PROMPT.md  LEARN_PROMPT.md  README.md
run.py, screener/, .screener_state.json    레거시(아래 참고, 온비드와 무관)
```

## 참고: 현대 하이브리드 스크리너(레거시)

루트의 `run.py`, `screener/`, `.screener_state.json`은 삭제된 "현대 하이브리드 중고 매물 주간 스크리닝" 루틴의 잔재이며
온비드와 무관하다. 원본은 브랜치 `claude/hyundai-hybrid-screening-bot-r0bn1c`에 있고, 필요 없으면 지워도 된다.
