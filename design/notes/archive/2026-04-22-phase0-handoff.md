# Grommy — Codex 인계용 핸드오프 문서

> 대상: 이 문서를 받는 Codex(또는 다른 AI 코딩 파트너)
> 현재 상태 기준일: 2026-04-22
> 핵심 산출물: `ui-mockup.html` (2+2 구조로 재설계된 단일 HTML 목업)
> 실제 배포: https://grommy.onrender.com (아직 v1. 이 작업의 타겟.)

---

## −1. 배포 현황 진단 (2026-04-22, Claude in Chrome 로 실제 확인)

**대전제: 현재 배포된 사이트는 아직 새 목업 이전 버전(v1)이다.** 랜딩 URL이 `?view=dashboard` 로 열리고, 사이드바는 6개(레퍼런스 허브 / 추출 실행 / 프롬프트 생성 / 프롬프트 라이브러리 / 설정 / 소개) + "데이터" 그룹(CSV·XLSX / Google Sheet)으로 구성돼 있다. 우측 채팅 패널(`<aside class="chat">`)은 대시보드/실행/생성/라이브러리/설정/소개 **모든 뷰에 상주**한다.

아래 12개 이슈는 실제 배포 화면에서 육안/DOM 레벨로 확인된 것이다. 심각도순.

### A. 구조적 (목업 이관으로 해결)

1. **우측 상주 채팅 패널이 모든 화면을 좁힌다.**
   - 현상: 소개/라이브러리/설정/대시보드에서 main 컬럼이 ~600px로 잘림. 소개 hero 타이포가 좌편향, 라이브러리 테이블이 3컬럼만 가능.
   - 해결: 채팅 `<aside>` 를 `data-view="studio"` 섹션 안으로 이동. 다른 뷰에는 렌더하지 않는다.

2. **랜딩이 여전히 대시보드.**
   - `?view=` 미지정 시 서버가 `view=dashboard` 로 튄다.
   - 해결: `render_home(requested_view or "about")` 로 기본값 교체 + 사이드바 `active` 도 `about` 로.

3. **사이드바가 6항목.** "레퍼런스 허브 / 추출 실행 / 프롬프트 생성 / 프롬프트 라이브러리 / 설정 / 소개".
   - 해결: 목업대로 "아카이브 / 스튜디오 // 설정 / 소개" 2+2 로 축소. "데이터" 그룹의 CSV·XLSX·Sheet 버튼은 **아카이브 뷰 topbar 안으로** 옮긴다.

4. **구 라우트가 404 대신 dead 렌더.**
   - 현재 `?view=dashboard|run|generate|library` 모두 각자의 서버 렌더 뷰를 돌려준다.
   - 해결: `dashboard → archive`, `run → archive`, `generate → studio`, `library → archive` 로 **302** 리다이렉트.

### B. 데이터/상태 버그

5. **라이브러리 카운트가 뷰마다 다르다 (정합성 버그).**
   - 레퍼런스 허브 / 프롬프트 생성 화면 → 사이드바 뱃지 "2" (대시보드의 `최근 저장된 결과` 테이블에도 2건 표시: "호텔 앞 시간 정지 및 충격파 연출", "비 오는 새벽 골목 시간 정지 및 인물 워킹").
   - 프롬프트 라이브러리 화면 → 사이드바 뱃지 "0", 본문 "아직 저장된 결과가 없습니다".
   - 원인 추정: 대시보드/생성 뷰는 `STATE.chat_refs` 같은 메모리 상태를 읽고, 라이브러리 뷰는 `read_results_table(config)` (CSV/metadata) 를 읽음 → 소스가 달라 값이 어긋난다.
   - 해결: 단일 소스 오브 트루스(`read_results_table` + `results_metadata`)로 통일. 사이드바 뱃지는 클라이언트 JS 가 `/api/library` 응답의 `count` 로 갱신.

6. **About 하단 CTA 가 dead route 로 간다.**
   - 현재 "원문 그루밍 시작" 버튼이 `?view=run` 으로 이동. 새 구조에선 `run` 없음.
   - 해결: `switchView('archive')` 로. (목업엔 이미 반영됨.)

### C. 브랜드/카피 일관성

7. **"그루밍" 단어가 기능 레이블에 남아 있다.**
   - 우측 채팅 헤더: "AI 시나리오 어시스턴트 · 아카이브 레퍼런스 기반 **그루밍**"
   - 생성 뷰 페이지 타이틀: "**그루밍** 작업공간"
   - 설정 블록: "**그루밍** 엔진 (Gemini)"
   - 채팅 제출 버튼: "**그루밍**"
   - 원칙(기확정): "그루밍" 은 About 내러티브에만 사용. 기능 레이블에는 넣지 않는다.
   - 치환안: 그루밍 엔진 → "Gemini API" · 그루밍 작업공간 → "스튜디오" · 그루밍(버튼) → "생성" · "레퍼런스 기반 그루밍" → "레퍼런스 기반 생성".

8. **placeholder 가 예시까지 담아서 UI처럼 보인다.**
   - 현재: "만들고 싶은 장면, 분위기, 카메라 무빙을 적어주세요. 예: 비 오는 밤, 시간이 멈춘 골목, 드론 샷으로 내려오며 주인공을 감싸는 장면"
   - 해결: placeholder 는 "시나리오를 자연스럽게 적어주세요" 한 줄. 예시는 preset chip 또는 "예시 보기" 토글로 분리.

### D. 기능 누락 (스튜디오 핵심)

9. **"구조화된 결과 블록" 자체가 없다.**
   - 목업의 가장 중요한 UX 결정(Scene / Subject / Camera / Light / Mood 5섹션 + Final EN 블록) 이 서버에 구현 안 됨. 현재는 우측 채팅에 평문으로 응답을 붙일 뿐이다.
   - 해결: §5.2 `POST /api/generate` JSON 계약 + Gemini 프롬프트를 5섹션 JSON 스키마로 업그레이드(`build_archive_groom_prompt`).

10. **프리셋 chip 의 정체성이 모호하다.**
    - 현재 생성 뷰 상단에 "빠른 카메라 태그 선택" 이라는 모호한 라벨로 chip 4개만 나열(Tracking shot / Dolly In / Long take / Medium shot). 유저는 이게 필터인지 생성 파라미터인지 알기 어렵다.
    - 해결: 목업 `preset-bar` 처럼 **"영상 길이 / 샷 타입 / 카메라 무빙"** 3개 그룹으로 라벨 명확화, 단일 선택 chip 으로 동작.

### E. 빈 상태 / 완성도

11. **빈 상태에 CTA 가 없다.**
    - 라이브러리 0건 → "아직 저장된 결과가 없습니다" 만 뜨고 dead end.
    - 실행 뷰 대기 상태 → "아직 실행된 작업이 없습니다. 링크를 넣고 시작하면 이곳에 진행 내역이 쌓입니다" — OK 한 카피지만 인접한 "새 추출 시작" CTA가 필요.
    - 해결: empty state 컴포넌트에 primary 버튼(`switchView('archive')`) 추가.

12. **상단 지표 카드가 대시보드에만 있다.**
    - "저장 결과 N · 추정 비용 ₩0" 가 대시보드 topbar 우상단에만 있고, 다른 뷰엔 없음.
    - 해결: 목업의 `archive-strip`(누적 프롬프트 / 성공률 / 이번 달 비용) 3개 카드로 **아카이브 뷰 전용** 영역에 이동. 다른 뷰에서는 안 보여준다.

### 저비용 선행 패치 (목업 이관 전이라도 바로 체감 개선)

Codex 에게 이관 전에 "임시로 먼저 넣을" 선택지. 무시하고 한방에 이관해도 됨.

- `render_home` 의 default view 를 `about` 으로 한 줄 변경.
- 우측 채팅 `<aside>` 출력을 `if current_view == "studio":` 로 감싸기.
- 사이드바 "데이터" 그룹 제거, CSV/XLSX/Sheet 버튼을 아카이브 뷰 topbar 로 이동.

이 3개만으로도 소개/라이브러리/설정에서 느껴지는 답답함의 대부분이 사라진다.

---

## 0-B. 실행 단계 (Phased Execution Plan) ⭐

**데드라인: 하루 안에 Phase 1~4 전부 완료.** Phase 당 2~3시간짜리 커밋 단위로 끊어서 연속으로 밀어붙인다. 단계를 나누는 이유는 "며칠 걸려서" 가 아니라 **배포를 쪼개서 한 단계가 깨져도 바로 뒤집기 위해서**다. 각 단계 간격은 최소(Render 빌드 3~5분) 로만 두고, 그 사이에 새 URL 1~2개만 클릭해서 확인 후 다음 단계 push.

전체 타임박스: **6~7시간 / 1영업일**.

```
08:00  Phase 1 push  →  08:10 확인  →  커밋
09:00  Phase 2 push  →  09:15 확인  →  커밋
12:00  Phase 3 push  →  12:30 확인  →  커밋
15:00  Phase 4 push  →  15:15 확인  →  커밋
16:00  전체 end-to-end 스모크 테스트 → 완료
```

한 단계가 예상보다 길어지면 **다음 단계를 축소**하되 Phase 1~3 은 반드시 같은 날 배포한다(Phase 3 를 내일로 미루면 스튜디오가 하루 더 깨진 상태로 노출됨). Phase 4(폴리싱)만 다음날로 미뤄도 허용.

### Phase 1 — Quick wins (약 30~45분, 구조 변경 없음)

목표: 기존 템플릿/라우팅 유지한 채 체감 답답함만 제거.

- `render_home(requested_view or "about")` 로 기본 뷰 교체. 사이드바 `active` 도 `about` 로.
- 우측 채팅 `<aside>` 출력부를 `if current_view == "studio":` 조건부로 감싼다(현재는 모든 뷰에 상주).
- "그루밍" 단어 기능 레이블에서 제거:
  - "그루밍 엔진 (Gemini)" → "Gemini API"
  - "그루밍 작업공간" → "스튜디오"
  - 채팅 제출 버튼 "그루밍" → "생성"
  - "AI 시나리오 어시스턴트 · 아카이브 레퍼런스 기반 그루밍" → "… 레퍼런스 기반 생성"
  - About 내러티브의 "그루밍"은 **유지**(브랜드 내러티브).
- 사이드바 "데이터" 그룹 제거. "CSV·XLSX 내보내기", "Google Sheet 열기" 버튼은 아카이브/라이브러리 뷰 topbar 의 actions 자리로 이동.
- 라이브러리 카운트 정합성 수정: 모든 뷰에서 사이드바 뱃지와 본문 카운트를 **동일한 소스**(`read_results_table(config)` 결과의 `len`)로 읽는다. STATE 메모리 기반 뱃지 제거.
- placeholder 단축: 우측 채팅 textarea placeholder 를 "시나리오를 자연스럽게 적어주세요" 한 줄로. 예시 장문은 삭제.

검증:
- `/?` 접속 시 소개 페이지가 풀 폭으로 렌더되는가.
- 라이브러리 뷰로 이동 후 사이드바 뱃지 숫자가 본문 카운트와 일치하는가.
- `/?view=settings` 에서 우측 채팅이 사라졌는가.

### Phase 2 — 템플릿 분리 + 2+2 사이드바 (약 2~3시간)

목표: `ui-mockup.html` 의 DOM 구조로 완전 이식. 기존 API 는 그대로 사용.

- `templates/index.html` 을 만들고 `ui-mockup.html` 본문을 이식. `render_home` 은 플레이스홀더만 치환하는 얇은 렌더러로 축소.
- 사이드바를 **2+2 (아카이브 / 스튜디오 // 설정 / 소개)** 로 재편. 나머지 4개 메뉴 제거.
- 구 라우트 리다이렉트:
  - `?view=dashboard` → `?view=archive` (302)
  - `?view=run` → `?view=archive`
  - `?view=generate` → `?view=studio`
  - `?view=library` → `?view=archive`
- Archive 뷰의 하드코딩 예시 테이블/지표를 제거, 클라이언트 JS 가 `/api/library` 로 페치해 채운다.
  - `archive-strip` 3개 숫자 = `/api/state` 의 `success_rate`, `current_session_cost`, `results_count`.
  - `filter-bar` chip count = `/api/library` 의 `camera_counts`.
  - `results` 테이블 row 는 `/api/library` 의 `rows` 로 렌더.
- Studio 뷰 DOM 구조만 이식. 아직 `/api/generate` 는 기존 `POST /generate` 그대로 쓰고, 응답을 result-block 이 아니라 임시로 단일 텍스트 영역에 렌더해도 OK (Phase 3 에서 교체).
- `switchView` 가 `history.pushState` 로 `?view=` 쿼리를 동기화하도록 확장.
- drawer(`openDrawer`) 데이터 소스를 `/api/library` 객체로 교체.

검증:
- 사이드바가 4개 항목으로 축소됐는가.
- 구 URL 로 접속 시 새 URL 로 302.
- 아카이브 테이블의 rows 가 실제 CSV 결과를 반영하는가(예시 하드코딩이 아니라).
- 새로고침해도 현재 `?view=` 가 유지되는가.

### Phase 3 — 스튜디오 결과 블록 + 새 /api/generate (약 2~3시간, 가장 큼)

목표: "구조화된 프롬프트 5섹션 + Final EN" 이 실제로 생성된다.

- `POST /api/generate` 신설. 요청/응답 스키마는 §5.2 참조.
- `build_archive_groom_prompt` 를 **Scene / Subject / Camera / Light / Mood** 5섹션 JSON 반환 스키마로 업그레이드. Gemini 에게 JSON 예시까지 넣어 구조 강제.
- `call_gemini_groom_prompt` 응답 파싱을 새 스키마에 맞춤. `fallback_groom_response` 도 동일 스키마로 갱신.
- Studio 클라이언트:
  - `preset-bar` 선택값(영상 길이 / 샷 타입 / 카메라 무빙) 을 hidden field 로 `/api/generate` 에 전송.
  - `pinned-card` 배열은 `localStorage['grommy.pins']` 에 저장, 생성 요청 시 `pinned_refs` JSON 으로 동봉.
  - 응답을 받아 `result-block` 의 5섹션 + `final-prompt` + `ref-tag(REF 1/2/3)` 렌더.
  - "아카이브에 저장" 버튼은 `POST /api/archive` (기존 `/save-generated` 를 alias) 로 전송.
  - "다시 생성" 은 마지막 payload 재전송.
  - `refine-bar` 입력은 "이전 결과를 이렇게 수정해서 다시 JSON 으로 달라" 지시어를 프롬프트 앞에 붙여 `/api/generate` 재호출.
- 구 `POST /generate` 는 한두 배포 동안 deprecated 유지 후 제거.

검증:
- 스튜디오에서 시나리오 + 프리셋 + 핀 3개로 생성 → 5섹션이 각각 채워지는가.
- `ref-tag` 가 실제로 참조한 핀 번호와 일치하는가.
- "아카이브에 저장" 후 아카이브 뷰로 이동 시 row 가 새로 추가돼 있는가.

### Phase 4 — 폴리싱 (약 1시간)

- 빈 상태 CTA: 아카이브 0건 화면에 "첫 링크를 붙여넣으세요 →" primary 버튼.
- 에러 토스트: `STATE.notice` 메시지를 topbar 아래 토스트 레이어로.
- 접근성: `preset-chip` 그룹에 `role=radiogroup`, 각 chip 에 `role=radio aria-checked`. `filter-bar chip` 에 `aria-pressed`. `pin-remove` 에 `aria-label="고정 해제"`.
- About 풀블리드: 우측 채팅이 사라졌으므로 hero 블록을 `max-width:960px; margin:0 auto;` 로 중앙 정렬.
- `?view=` pushState 가 브라우저 back/forward 와 정상 연동되는지 점검.
- 모바일/태블릿(1180px 이하): `archive-layout`, `studio-layout` 이 단일 컬럼으로 떨어지는지 확인.

### Phase 5 (옵션) — Flask + Jinja 이관

장기적으로 React/Vite 로 갈 예정이면 여기서 프레임워크를 바꿔 두는 게 저렴하다. 당장 급하지 않으면 미뤄도 됨. BaseHTTPRequestHandler → Flask 전환 + 템플릿을 Jinja 로 재정리.

### 단계별 의존 관계 (요약)

```
Phase 1  (독립, 바로 배포 가능)
  └─ Phase 2  (Phase 1 의 카피/뱃지 수정 전제)
       └─ Phase 3  (Phase 2 의 스튜디오 DOM 전제)
            └─ Phase 4  (Phase 3 의 스튜디오 기능 전제)
                 └─ Phase 5  (옵션, 나머지와 독립)
```

각 단계는 Render 자동 배포 1회 분리. Phase 3 만 예외적으로 Gemini 프롬프트 템플릿 변경 + 서버 API 변경을 같은 배포에 묶는 게 합리적(중간 상태가 더 꼬임).

---

## 0. 이 문서가 다루는 범위

이 문서는 **디자인(목업)과 실제 서비스(web_app.py)를 붙이는 작업**을 Codex에게 넘기기 위한 인수인계서다.
- 목업은 `ui-mockup.html` 한 파일에 CSS/JS까지 전부 들어 있는 정적 파일이다.
- 실제 백엔드는 `web_app.py` 내부의 `PromptExtractorHandler`(파이썬 표준 `BaseHTTPRequestHandler`) + `extract.py`(영상 다운로드 → 프레임 OCR → Gemini 호출 → CSV/Sheet 저장 파이프라인) 로 이미 동작 중이다.
- 즉 Codex가 할 일은 **"목업의 구조를 기준으로 web_app.py가 렌더하는 HTML 템플릿과 라우팅을 새 구조에 맞게 재배치하고, 필요한 API만 몇 개 추가하는 것"** 이다.

---

## 1. 제품 철학 (한 줄 요약)

**Grommy = "좋은 영상 프롬프트를 긁어모으고(아카이브), 그걸 참조해서 시네마틱한 새 프롬프트를 만든다(스튜디오)".**

유저가 서비스에서 하는 일은 딱 두 가지다.

1. **아카이빙 자동화** — 영상 링크(Instagram Reels / YouTube Shorts 등)를 붙여넣으면, Gemini가 영상에서 프롬프트를 추출해 이 사이트와 Google Sheet에 동시에 쌓아둔다.
2. **시네마틱 프롬프트 구조화 & 창조** — 아카이브를 참조(pin)하고, 시나리오 텍스트 + 프리셋(영상 길이 / 샷 타입 / 카메라 무빙)을 주면, Gemini가 Scene / Subject / Camera / Light / Mood 5개 섹션으로 구조화된 프롬프트 + 최종 Final EN 프롬프트를 만들어 준다. 결과는 다시 아카이브에 저장할 수도, SeaDance / Higgsfield 같은 영상 생성 서비스로 던질 수도 있다.

---

## 2. IA (정보 구조) — 2+2 사이드바

| 그룹 | 메뉴 | 라우트 키 (data-view) | 역할 |
| --- | --- | --- | --- |
| 핵심 흐름 | 아카이브 | `archive` | 링크 추출 + 저장된 프롬프트 리스트 (검색/필터/상세 드로어) |
| 핵심 흐름 | 스튜디오 | `studio` | 참조 고정 + 시나리오 → 구조화 프롬프트 생성 |
| 보조 | 설정 | `settings` | Gemini API 키, Sheet 연동, 배포 상태 |
| 보조 | 소개 | `about` | 랜딩 페이지 (기본 active) |

- 기본 랜딩은 `about` 이다. 사이드바에서 `nav-item.active` 가 `about` 에 붙어 있다.
- "대시보드", "실행", "생성(Generate)", "라이브러리" 같은 과거 탭은 **전부 제거**됐다. 이전 백엔드 라우트(`?view=dashboard`, `?view=run`, `?view=generate`, `?view=library`)는 전부 `archive` 또는 `studio` 로 매핑해야 한다.

---

## 3. 목업 파일 구조 (ui-mockup.html)

- 한 파일, 약 2590 라인. `<style>` 내부에 전체 스타일이 있고 `<script>` 내부에 switchView / 드로어 / 프리셋 chip 토글 로직이 있다.
- 주요 CSS 변수(디자인 토큰): `:root { --bg, --surface, --ink, --muted, --line, --accent(#2f6a54), --accent-hover, --success, --warn, --fail, --radius-*, --shadow-* }` — `main .content` 가 배경 `--bg`, 카드는 `--surface`, 강조색은 Grommy 그린.
- 폰트: Pretendard (CDN) → fallback 은 system sans.
- 섹션 전환: `.view` 에 `active` 클래스가 붙은 것만 display. 단 하나만 active 가정.

### 3.1 Archive 뷰 (`data-view="archive"`)

```
topbar(페이지 타이틀 + Gemini 연결 상태 · CSV/Sheet 버튼)
archive-strip (3개 지표 카드: 누적 프롬프트 / 추출 성공률 / 이번 달 비용)
archive-layout (grid 420px 1fr)
  ├ archive-extract (sticky left)
  │   ├ input-wrap (tabs: 링크 붙여넣기 / 파일 / 클립보드) + textarea + 추출 버튼
  │   └ progress-card (진행 바 + 건별 activity list)
  └ archive-list (right)
      ├ results-toolbar (search + 고급 필터 / 초기화)
      ├ filter-bar (카메라 워킹 chip들)
      └ results-table-wrap > table.results (열: 썸네일 / 카메라 / 프롬프트 / 내용 / 메타 / 액션)
            → row 클릭 = openDrawer(this) 로 상세 슬라이드 드로어
```

### 3.2 Studio 뷰 (`data-view="studio"`)

```
topbar(Gemini 2.5 Flash · 참조 규칙 24개 상태 + 초기화)
studio-layout (grid 280px 1fr)
  ├ studio-side (sticky left, 참조 고정)
  │   ├ pin-head (+ 추가 → switchView('archive'))
  │   ├ pinned-card × 3 (번호 · 이름 · 태그 · excerpt · ✕)
  │   └ pin-empty (placeholder)
  └ studio-main (right)
      ├ scenario-card
      │   ├ textarea.scenario-input
      │   ├ preset-bar (영상 길이 / 샷 타입 / 카메라 무빙 — 각 group 단일 선택 chip)
      │   └ scenario-run (⌘+Enter hint + 시네마틱 프롬프트 생성 버튼)
      ├ result-block (이 서비스의 핵심 블록)
      │   ├ result-head (아이콘 + 제목 + 요약 + 참조·비용 메타)
      │   ├ result-sections (grid 1fr 1fr)
      │   │   SCENE / SUBJECT / CAMERA / LIGHT / MOOD(full width)
      │   │   각 섹션 body 안에 `<span class="ref-tag">REF n</span>` 로 어떤 참조에서 왔는지 표시
      │   ├ final-prompt (다크 배경 #1d2a24, monospace, 우상단 copy-btn)
      │   └ result-actions (아카이브에 저장 / 씨댄스로 보내기 / spacer / 다시 생성)
      └ refine-bar (inline 수정 입력 + 다듬기 버튼) + refine-history
```

### 3.3 Settings / About 뷰

- Settings: 기존 `web_app.py` 템플릿에서 쓰던 것과 구조가 유사. 좌측 `settings-nav` + 우측 카드들. `POST /settings` 로 key=value 제출하면 되는 기존 계약 유지.
- About: 브랜드 스토리 + CTA 2개(아카이브로 이동 / 스튜디오 열기). 랜딩 기본값.

---

## 4. 프론트엔드 변경사항

> 현재 `web_app.py` 는 서버 사이드에서 HTML 문자열을 생성한다(`render_home`, `_render_brand_block` 등). 템플릿 파일이 따로 없고 파이썬 문자열 안에 f-string으로 HTML이 박혀 있다.

### 4.1 큰 방향 (택 1)

**(A) 점진 이전 (권장)**
1. `ui-mockup.html` 을 Jinja2 템플릿 엔진 없이 쓸 수 있도록 **기본은 정적 HTML로 서빙**하고, 필요한 구간만 서버가 주입.
2. 정적 리소스는 `web_app.py` 같은 폴더의 `static/` 또는 `templates/` 로 옮긴다.
3. `PromptExtractorHandler.render_home` 은 템플릿을 읽어 `{{ slot_name }}` 플레이스홀더만 치환하는 방식으로 바꾼다.
4. 뷰별 동적 데이터(최근 결과, 통계, 채팅 등)는 **클라이언트가 fetch() 로 API 호출**해서 채운다(이미 `/api/state`, `/api/library`, `/api/deployment` 가 있음).

**(B) 완전 재작성**
- Flask / FastAPI + Jinja2 로 갈아타고 기존 BaseHTTPRequestHandler 를 폐기.
- 유저가 추후 React 로 넘어갈 여지를 보면 이 쪽이 깔끔하지만, 지금 작업량이 크다.

권장: **A**. `BaseHTTPRequestHandler` 유지 + 템플릿 파일 분리 + 클라이언트 사이드 렌더링 확대.

### 4.2 구체 작업 (A 기준)

1. **템플릿 분리.**
   - `templates/index.html` = `ui-mockup.html` 을 복사하고, 서버 주입이 필요한 곳에 `{{BRAND_BLOCK}}`, `{{INITIAL_VIEW}}`, `{{NOTICE}}` 같은 플레이스홀더만 남긴다.
   - `_render_brand_block()` 이 반환하는 SVG 로고 블록은 그대로 유지하되, 목업의 `.brand` 자리에 주입한다.
2. **라우팅 재매핑.**
   - 기존 `/?view=dashboard|run|generate|library` 요청이 들어오면 `301` 로 `/?view=archive` 또는 `/?view=studio` 로 리다이렉트.
   - `?view=` 미지정이면 `about` 을 active 로.
3. **Archive 뷰 동적 데이터.**
   - 서버 초기 렌더에는 하드코딩 예시 테이블을 **전부 제거**하고, `<tbody id="archiveRows"></tbody>` 로 비워둔 뒤 클라이언트에서 `fetch('/api/library')` 결과로 채운다.
   - `archive-strip` 의 3개 숫자도 `/api/state` → `runtime.success_rate`, `runtime.current_session_cost`, `results_count` 로 매핑.
   - 필터 `chip` 의 카운트(`<span class="count">32</span>`)는 `/api/library` 의 `camera_counts` 응답으로 채운다.
   - 검색창: 간단하게는 프런트에서 in-memory 필터. 결과가 많아지면 `/api/library?q=...` 로 서버 필터링 추가.
4. **Studio 뷰 동적 데이터.**
   - `pinned-card` 들은 로컬스토리지가 아니라(❗ Claude artifact 제약과 무관, 실제 브라우저에선 사용 가능) **서버 세션 혹은 쿼리 파라미터**로 유지한다.
     - 간단 구현: 클라이언트 JS 가 `localStorage['grommy.pins']` 에 `[{url, name, tags, excerpt}]` 저장.
     - 서버가 뭔가 해야 하는 것은 생성 요청 시 이 배열을 `pinned_refs`(기존 `/generate` 계약) JSON 문자열로 함께 POST 하는 것.
   - `preset-bar` 의 선택값은 hidden input 세 개(`duration`, `shot_type`, `camera_move`)로 `/generate` 에 함께 전송.
   - `scenario-input` 의 placeholder 값은 이미 있다. 서버로는 `message` 필드로 전송(기존 계약과 동일).
   - **결과 렌더**: 현재 `/generate` 는 redirect 후 `STATE.chat` 배열에 append 하고 있다. 새 UI에서는 redirect 대신 **`POST /api/generate` 엔드포인트를 새로 만들고 JSON 응답**을 받아 `result-block` DOM 을 업데이트하는 것이 자연스럽다. (§5.2 참조)
   - `ref-tag(REF 1/2/3)` 은 `call_gemini_groom_prompt` 응답의 `reference_indexes` 를 활용하면 그대로 매핑 가능.
5. **JS 정리.**
   - 이미 `ui-mockup.html` 말미에 있는 스크립트 블록(view switch, chip toggle, drawer, preset-chip, pin-remove, copy-btn) 은 유지.
   - `switchView` 는 `history.pushState` 로 `?view=` 쿼리도 같이 갱신하도록 확장(새로고침 시 같은 뷰 유지).
6. **드로어(`.drawer`) 데이터 주입.**
   - 현재는 row DOM 에서 긁어와 채우는 데모 로직. 실제로는 row 에 `data-url`, `data-index` 를 붙여두고, openDrawer 가 `/api/library` 전체 배열에서 매칭 객체를 찾는 방식으로 교체.
7. **Settings 폼.**
   - 목업 쪽은 아직 예시 수준. 기존 `web_app.py` 의 `POST /settings` 필드명(`gemini_api_key`, `google_sheet_id`, `worksheet`, ...)을 그대로 사용해 **필드명만 일치**시킨다.
8. **About CTA.**
   - `switchView('archive')`, `switchView('studio')` 로 이미 변경돼 있다. 링크 클릭이 아니라 쿼리 푸시 기반이므로 SEO가 필요하면 내부 링크로도 동시 노출.

### 4.3 접근성 / 반응형 잔업

- `.preset-chip` 들은 role=radiogroup / role=radio + aria-checked 붙이기.
- `.chip` 필터는 role=button aria-pressed.
- `.pinned-card` ✕ 버튼은 aria-label="고정 해제".
- 1180px 이하에서 `archive-layout`, `studio-layout` 이 단일 컬럼이 되는 미디어 쿼리는 이미 들어 있다. 검토만.
- 다크 모드는 현재 미지원. Codex 판단으로 토글 필요하면 토큰 구조만 따라 색만 재정의.

---

## 5. 백엔드 변경사항

### 5.1 라우트 현황 요약

| 메서드 | 경로 | 현재 동작 | 새 구조에서의 변경 |
| --- | --- | --- | --- |
| GET | `/` | 모든 뷰를 한 HTML로 서버 렌더 | 템플릿 파일을 읽어 **플레이스홀더만 주입**하고 그 외 데이터는 JSON API 로 |
| GET | `/api/state` | 실행 상태/누적 지표 JSON | 그대로 유지. archive-strip 3개 숫자에 재사용 |
| GET | `/api/library` | 최근 결과 rows + camera_counts JSON | 그대로 유지. 쿼리 `q`, `camera` 추가(§5.3) |
| GET | `/api/deployment` | 배포/Git 상태 | 그대로. Settings 화면에서 사용 |
| GET | `/download/csv` / `/download/xlsx` | 현재 CSV/XLSX 다운로드 | 그대로 |
| GET | `/ping` | 헬스체크 | 그대로 |
| POST | `/run` | 링크 추출 시작(백그라운드 worker) | 그대로. 단 성공 시 `Location: /?view=archive` 로 변경 |
| POST | `/generate` | 채팅 append 후 redirect | **`POST /api/generate` 추가** (§5.2) — 기존은 1개 리비전만 더 유지한 뒤 deprecate |
| POST | `/save-generated` | 채팅 결과를 result_table 에 저장 | `POST /api/archive` 로 alias 권장 |
| POST | `/settings` | 설정 저장 | 그대로 |

### 5.2 신규 `POST /api/generate` (JSON 계약 제안)

요청:

```json
{
  "scenario": "비 오는 밤 도시의 뒷골목…",
  "duration": "10s",
  "shot_type": "Medium",
  "camera_move": "Steadicam follow",
  "pinned_refs": [
    { "링크": "https://…", "내용": "…", "카메라 워킹": "스테디캠" }
  ]
}
```

응답:

```json
{
  "sections": {
    "scene":   { "body": "Rain-soaked urban back alley…", "ref_indexes": [1] },
    "subject": { "body": "A lone figure in a dark coat…", "ref_indexes": [] },
    "camera":  { "body": "Steadicam follow from behind…", "ref_indexes": [2] },
    "light":   { "body": "Cold neon magenta–cyan…",       "ref_indexes": [] },
    "mood":    { "body": "Cinematic noir atmosphere…",    "ref_indexes": [3] }
  },
  "final_prompt_en": "A hyper-realistic cinematic shot…",
  "summary_ko": "시간이 멈춘 밤거리 시퀀스…",
  "camera_tags": ["Steadicam", "Arc"],
  "reference_indexes": [1, 2, 3],
  "usage": { "krw_estimate": 38.2, "model": "gemini-2.5-flash" },
  "meta": "Gemini 그루밍 완료 · 참조 3개"
}
```

구현 포인트:
- 핵심 호출부(`call_gemini_groom_prompt`, `fallback_groom_response`) 는 이미 있다. **프롬프트 템플릿만 5개 섹션 구조로 업그레이드** 하면 된다(`build_archive_groom_prompt` 수정).
- 현재는 응답에서 `prompt_en`, `reply_ko`, `summary_ko`, `camera_tags`, `reference_indexes` 를 뽑아 단일 필드 `prompt` 로 합쳐서 쓴다. 섹션화를 위해 Gemini 프롬프트에 JSON schema 예시를 명시(`scene/subject/camera/light/mood` 키를 가진 객체 반환 요구).
- `STATE.add_chat_pair` 같은 서버 사이드 채팅 히스토리는 **스튜디오 뷰에선 더 이상 필요 없다**. 대신 생성 결과를 그대로 응답만 주고, 저장은 유저가 "아카이브에 저장" 버튼을 눌렀을 때 `/api/archive` 호출로 수행.

### 5.3 `/api/library` 확장

- 쿼리: `q`(자유 텍스트), `camera`(카메라 워킹 필터 복수 가능, 콤마 구분), `limit`, `offset`.
- 응답에 `total`, `facets.camera_counts`, `facets.source_counts` 를 추가해 프런트에서 chip 카운트와 페이지네이션을 바로 그릴 수 있게.
- 내부적으론 `read_results_table` 결과를 파이썬에서 필터. row 수가 많지 않아 지금 당장 DB 안 넣어도 된다.

### 5.4 `/api/run` 상태 폴링

- 현재 `/api/state` 가 이미 worker 진행률을 돌려준다. 프런트는 Archive 뷰 `progress-card` 를 **실행 중일 때만** 보이게 하고, `running: true` 인 동안 1초 간격으로 polling.
- 실행 중이 아닐 때는 `progress-card` 대신 "최근 실행 요약"(완료/실패 수, 비용)만 정적으로 표시.

### 5.5 Sheet 동기화

- `sync_to_google_sheet`, `delete_google_sheet_row`, `clear_google_sheet_results` 는 그대로. 신규 UI 에서 "Sheet 열기" 버튼은 `config.google_sheet_id` 로 URL 생성 후 새 탭.
- 생성된 프롬프트를 아카이브에 저장할 때도 기존 `save_generated_result` 경로가 CSV + Sheet 동시 기록하므로 계약 유지.

### 5.6 보안/키 관리

- Gemini API 키는 이미 `secret_store` → OS keychain / env var fallback 구조. 그대로 두고, Settings UI 에서 마스킹 입력만 신경.
- `POST /settings` 호출 시 키 유효성은 `validate_gemini_api_key` 가 처리한다.

---

## 6. 데이터 스키마 (현재 CSV 컬럼 기준)

`extract.py` 가 쓰는 row 의 표준 컬럼 — Archive 뷰의 결과 테이블이 이걸 그대로 소비한다.

| 컬럼 | 의미 | UI 매핑 |
| --- | --- | --- |
| 링크 | 원본 영상 URL (또는 `grommy://generated/...`) | `.clickable-row` data-url, meta-link href |
| 썸네일 | 로컬 썸네일 파일 경로 | `.thumb` (현재는 IG/YT 텍스트. 실제로는 이미지 src) |
| 카메라 워킹 | 쉼표로 구분된 태그들 | `.tag-row .tag` |
| 프롬프트(영문) | Gemini 결과 EN 프롬프트 | `.prompt-text` |
| 내용 | 한국어 요약 | `.content-text` |
| 메타 | 생성 시간 / 비용 | `.meta-col` |
| 소스 | instagram / youtube / grommy | `.thumb` 라벨 결정 |

`normalize_result_row` 가 위 키들을 보장한다. 신규 코드에서도 이 형태를 유지할 것.

---

## 7. 남은 UX 디테일 (목업이 아직 정적인 부분)

1. **추출 진행률 실시간 갱신** — activity list 의 ✓/✕ 색깔 도트는 `/api/state` 의 `items[].success` 로 바인딩해야 한다.
2. **빈 상태(empty state)** — 아카이브 0건일 때: "링크를 하나 붙여 보세요" CTA. 현재 목업은 예시 rows 5개가 고정 박혀 있다.
3. **에러 배너** — 기존 `STATE.set_notice` 메시지를 topbar 아래에 토스트로 띄우는 얇은 레이어 필요.
4. **Pin 추가 플로우** — 드로어에서 "★ 고정" 버튼이 아직 없다. drawer-actions 에 추가하고, 클릭 시 `localStorage['grommy.pins']` + 스튜디오 패널 실시간 갱신 이벤트(`window.dispatchEvent(new CustomEvent('pins:changed'))`).
5. **결과 재생성** — `result-actions` 의 "다시 생성" 은 마지막 payload 를 캐시해 두고 그대로 재요청.
6. **Refine(다듬기)** — `refine-bar` 의 입력은 마지막 결과 + 사용자 수정 지시를 묶어 `/api/generate` 에 다시 POST. 서버 프롬프트는 "이전 결과를 이러이러하게 수정해서 다시 JSON으로 내놓아라" 지시문을 프롬프트 앞에 추가.
7. **영상 생성 서비스 연동 — "씨댄스로 보내기"** — 현재는 버튼만 있다. 시나리오: 최종 프롬프트를 클립보드에 복사하고 `window.open` 으로 SeaDance / Higgsfield 탭 열기. OAuth/직접 호출이 필요하면 별도 이슈.

---

## 8. 작업 우선순위 (제안)

1. **템플릿 파일 분리** + `/?view=old → new` 리다이렉트. (작업량 小, 파급력 大)
2. **Archive 뷰의 테이블/지표를 `/api/library`·`/api/state` 로 바인딩.** (하드코딩 예시 제거)
3. **Studio 뷰 `POST /api/generate` 신설** + Gemini 프롬프트 스키마를 5섹션 JSON 으로 변경.
4. **Pin/refine 클라이언트 로직** — localStorage 기반.
5. **미세 조정** — 접근성, 에러 배너, 빈 상태, `?view=` pushState.
6. **(옵션) Flask 재작성** — 이후 React/Vite 로 넘어갈 계획이면 이 시점에.

---

## 9. 체크리스트 (Codex 에게)

- [ ] `ui-mockup.html` 을 기준으로 `templates/index.html` 를 만들고 `PromptExtractorHandler.render_home` 을 단순 치환 렌더러로 교체한다.
- [ ] 구 라우트 4개(`dashboard/run/generate/library`) 를 `archive/studio` 로 리다이렉트.
- [ ] Archive 하드코딩 테이블 삭제, 클라이언트 JS fetch 연결.
- [ ] 카메라 chip/지표 카드 데이터 바인딩.
- [ ] `POST /api/generate` 추가, 5섹션 JSON 응답.
- [ ] Gemini 프롬프트 템플릿을 5섹션 JSON 으로 업그레이드(build_archive_groom_prompt).
- [ ] Studio 의 preset, pin 상태를 `localStorage + 폼 hidden field` 로 유지.
- [ ] drawer openDrawer 를 `/api/library` 객체로부터 채우도록 교체.
- [ ] `/api/library` 에 `q`/`camera`/`limit`/`offset` + `facets` 추가.
- [ ] About CTA, Settings 내비 확인(이미 적용).
- [ ] `switchView` 가 `?view=` 쿼리 pushState 하도록 확장.
- [ ] 테스트: 링크 1건으로 추출 → 아카이브에 rows 증가, Studio에서 pin→scenario→generate→final prompt 렌더까지 end-to-end 성공 확인.

---

## 10. 관련 파일

- `ui-mockup.html` — 이 문서의 단일 ground truth 디자인.
- `ui-mockup-v1.html` — 이전 버전(백업).
- `web_app.py` — 서버 엔트리, 라우터, 템플릿 렌더러. 수정 타겟.
- `extract.py` — 파이프라인 유틸. 대체로 건드리지 않음(Gemini 프롬프트 템플릿만 5섹션화).
- `grommy-logo*.png` / `grommy-logo.svg` — 브랜드 자산.
- `최근작업정리.md`, `배포가이드.md`, `사용법.md` — 운영/배포 히스토리 참고용.

---

## 11. 합의된 UX 원칙 (변경 시 다시 논의 필요)

- 사이드바는 2+2 고정. 채팅은 **스튜디오 화면에만** 존재. 우측 상주 패널 없음.
- 스튜디오의 시각적 주인공은 **구조화된 결과 블록(result-block)** 이다. 다른 요소보다 visually dominant 해야 한다.
- 브랜드 톤 "그루밍"은 About 페이지 내러티브와 일부 힌트 텍스트에만 사용. 기능 레이블에는 쓰지 않는다(아카이브/스튜디오/추출/생성).
- 기본 랜딩은 About.
