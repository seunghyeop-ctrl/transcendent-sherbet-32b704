# Grommy — Phase 2 지시서 (UX 리뷰 #2)

> 대상: Codex (또는 이 repo를 이어받는 AI 코딩 파트너)
> 작성일: 2026-04-23
> 작성자: Claude (UX/UI 디자이너 역할)
> 이전 사이클: `archive/2026-04-22-phase0-handoff.md`, `archive/2026-04-22-phase1-result.md`
> 베이스 커밋: main HEAD (Phase 1 병합본)

---

## 0. 이번 사이클 요약

Phase 1 (사이드바 2+2, 브랜드 통일, 우측 상주 채팅 제거, legacy view alias 추가)은 **부분 성공**. 사이드바/브랜딩/채팅 레이아웃은 OK. 하지만 **본문 렌더링이 legacy view 로 오면 빈 화면**이 나온다. 이번 Phase 2의 목표는 **본문을 확실히 잡는 것**이다.

---

## 1. Phase 1 결과 진단 (Claude in Chrome, `?view=dashboard` 직접 접속)

### ✅ 반영 확인된 것
- 사이드바: `아카이브 / 스튜디오` + `보조` 그룹의 `설정 / 소개` **4 항목 2+2** 로 축소 완료.
- 로고 자리에 **Grommy G** 아트워크와 워드마크 노출.
- 사용자 하단 풋터 `Seunghyeop · Local · 자동 저장됨`.
- 우측 상주 채팅 `<aside class="chat">` **제거됨** (본문 영역이 전폭으로 확장).

### ❌ 아직 안 된 것
1. **랜딩이 `/?view=dashboard` 로 튕김.** → `/` 로 열면 기본값이 `about` 이어야 한다 (Phase 1 핸드오프 2번 항목).
2. **legacy view 가 빈 화면.** `?view=dashboard` 로 들어가면 사이드바만 있고 **본문이 통째로 공백**. `LEGACY_VIEW_ALIASES` 가 *파이썬 상수로는 추가됐지만* 실제 라우팅 경로에서 `requested_view` 치환/302 가 걸리지 않거나, 치환된 뒤에도 `archive` / `studio` 템플릿 섹션이 렌더되지 않는다. **최우선 버그.**
3. 아카이브/스튜디오 탭 직접 클릭 시의 본문 상태(데이터 카드, 필터 바, 테이블, 결과 블록)는 Chrome 확장 재연결 이슈로 이번 사이클에서 육안 확인 실패. **Codex가 직접 열어서 현재 렌더 결과를 확인하고 스크린샷 근거로 결정할 것.**

---

## 2. Phase 2 범위

Phase 2 의 딱 세 가지.

### P2-1. 라우팅 정확히 동작시키기 (가장 급함)

`web_app.py` 의 `render_home()` 진입부를 다음 원칙으로 정리:

```
if requested_view is None or requested_view == "":
    requested_view = "about"           # 랜딩 기본값: 소개
elif requested_view in LEGACY_VIEW_ALIASES:
    return redirect_302(f"/?view={LEGACY_VIEW_ALIASES[requested_view]}")
elif requested_view not in VALID_VIEWS:
    return redirect_302("/?view=about")  # 알 수 없는 뷰도 소개로
```

- **302** 를 쓴다 (301 금지 — 구 URL이 캐시/북마크에 영구 박히면 나중에 돌이키기 힘듦).
- 리다이렉트 후 도착 URL에서는 **실제 본문이 비어있지 않아야** 한다.
- 사이드바 `active` 상태도 치환된 `requested_view` 기준으로 계산해 하이라이트가 본문과 일치해야 한다.

### P2-2. 목업의 `data-view="archive"` / `data-view="studio"` 섹션을 **서버가 직접 렌더**

Phase 1 에서 `ui-mockup.html` 을 템플릿 원본으로 쓰는 건 유지하되, `render_home()` 이 뷰별로 다음을 주입해야 한다:

- `archive` 뷰:
  - `archive-strip` 카드 3개 (누적 프롬프트 / 성공률 / 이번 달 비용) — 현재 값은 0/—/₩0 라도 **div 자체는 반드시 렌더**.
  - 상단 topbar 에 URL 입력 + 시작 버튼 + CSV·XLSX·Sheet 다운로드 버튼 그룹 (구 `데이터` 사이드바 그룹 이주).
  - 하단에 라이브러리 테이블 (저장된 결과 목록 + 빈 상태 CTA).
- `studio` 뷰:
  - 상단 preset-bar 3그룹 (영상 길이 / 샷 타입 / 카메라 무빙) — 단일 선택 chip.
  - 중앙에 채팅 대화 (기존 `<aside class="chat">` 의 내용이 여기로 이주).
  - 하단에 **구조화된 결과 블록 자리** (Scene / Subject / Camera / Light / Mood 5 섹션 + Final EN). Phase 3에서 실제 API 연결 전까지는 **플레이스홀더 카드 5개 + 빈 Final EN 코드블록** 으로 놔둘 것.
- `settings`, `about` 은 Phase 0 검토에서 이미 OK 판정. 손대지 말 것.

**❗ 금지:** 새 HTML 파일을 만들지 말 것. `ui-mockup.html` 하나만 템플릿 소스로 유지. 뷰 스위칭은 서버가 주는 `data-active-view` 속성으로 결정되게.

### P2-3. 라이브러리 카운트 단일 소스 통일 (Phase 0 5번 항목)

- 사이드바 `아카이브` 옆 뱃지는 **`/api/library`** 의 `count` 필드 하나만 본다.
- `/api/library` 는 `read_results_table(config)` 결과 길이를 리턴한다.
- 기존의 `STATE.chat_refs` 는 **더 이상 카운트 소스가 아니다** (채팅 메시지 참조 컨텍스트로만 사용).

---

## 3. 테스트 체크리스트 (Codex가 끝내기 전에 반드시 통과)

아래 10개 URL 을 직접 열어서 **본문이 비지 않고, 사이드바 active 가 맞고, 콘솔 JS 에러 없음** 확인:

| URL | 기대 결과 | active |
|-----|----------|--------|
| `/` | 소개 뷰 렌더 | `소개` |
| `/?view=about` | 소개 뷰 렌더 | `소개` |
| `/?view=archive` | 아카이브 뷰 (카드 + topbar + 테이블) | `아카이브` |
| `/?view=studio` | 스튜디오 뷰 (preset + 채팅 + 결과 블록) | `스튜디오` |
| `/?view=settings` | 설정 뷰 | `설정` |
| `/?view=dashboard` | 302 → `/?view=archive` | `아카이브` |
| `/?view=run` | 302 → `/?view=archive` | `아카이브` |
| `/?view=generate` | 302 → `/?view=studio` | `스튜디오` |
| `/?view=library` | 302 → `/?view=archive` | `아카이브` |
| `/?view=garbage` | 302 → `/?view=about` | `소개` |

빈 본문이 하나라도 나오면 미완.

---

## 4. 경계선 (Phase 2에서는 건드리지 말 것)

- `POST /api/generate` 의 JSON 계약 변경 (Phase 3 스코프).
- Gemini 5섹션 스키마 프롬프트 (Phase 3).
- empty state CTA 카피 마무리 (Phase 4).
- 로고/파비콘 교체 (Phase 4).

---

## 5. 완료 신호

Codex 가 Phase 2 를 끝냈다고 보고할 때 커밋 메시지에 반드시 포함할 것:

```
phase2: server-rendered archive/studio views + legacy 302

- default view is `about` (was `dashboard`)
- LEGACY_VIEW_ALIASES enforced via 302
- archive view: 3 cards + topbar + library table
- studio view: preset-bar + chat + structured-result placeholder
- library count = /api/library count (single source)

Tested: / /?view=about /?view=archive /?view=studio /?view=settings
        + dashboard/run/generate/library/garbage all 302
```

그리고 push 후 `https://grommy.onrender.com/?view=archive` 에 실제 콘텐츠가 떠 있어야 내 다음 사이클이 시작된다.

---

## 6. 참고

- 목업 최종본: 루트 `ui-mockup.html`.
- 목업 이전본(6뷰): 루트 `ui-mockup-v1.html`. **참조 전용, 수정 금지.**
- Phase 0 상세 맥락: `archive/2026-04-22-phase0-handoff.md`.
- Phase 1 진단 원본: `archive/2026-04-22-phase1-result.md`.
