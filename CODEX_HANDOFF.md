# CODEX HANDOFF

최종 업데이트:
- 2026-04-23

기준 브랜치:
- `main`

현재 HEAD:
- `79d2cc2` `design(phase2): UX review after phase1 live check`

원격 저장소:
- `https://github.com/seunghyeop-ctrl/transcendent-sherbet-32b704.git`

## 현재 상태 요약

- Phase 1 결과 리뷰가 `design/notes/archive/2026-04-22-phase1-result.md` 에 정리되어 있음
- 다음 작업 기준 문서는 `design/notes/latest-review.md`
- 현재 저장소는 원격과 동기화된 깨끗한 상태였고, 이 핸드오프 문서와 최근 작업 요약만 추가 예정
- 핵심 디자인/백엔드 작업은 `ui-mockup.html` + `web_app.py` 조합으로 이어가면 됨

## 다음 작업 우선순위

반드시 아래 문서 기준으로 진행:
- `design/notes/latest-review.md`

현재 기준 지시:
- **Phase 2 진행**

핵심 목표:
1. `/` 기본 랜딩을 `about` 으로 고정
2. legacy view (`dashboard`, `run`, `generate`, `library`) 를 새 view 로 302 리다이렉트
3. `archive`, `studio` 본문을 `ui-mockup.html` 기준으로 서버 렌더
4. 라이브러리 카운트를 `/api/library` 단일 소스로 통일

## 꼭 확인할 파일

- `design/notes/latest-review.md`
- `design/notes/archive/2026-04-22-phase1-result.md`
- `ui-mockup.html`
- `web_app.py`
- `최근작업정리.md`

## 실행 방법

```bash
cd "/Users/seunghyeop/Documents/Claude/Projects/프롬프트 추출 및 분류 작성 자동화 프로그램 개발"
python3 app.py
```

기본 확인 주소:
- `http://127.0.0.1:5007/`
- `http://127.0.0.1:5007/?view=about`
- `http://127.0.0.1:5007/?view=archive`
- `http://127.0.0.1:5007/?view=studio`
- `http://127.0.0.1:5007/?view=settings`

## Phase 2 완료 조건

`design/notes/latest-review.md` 의 체크리스트를 기준으로, 아래가 모두 맞아야 함.

- `/` → `about`
- `dashboard/run/generate/library/garbage` → 302 정상 동작
- `archive` 본문이 비어 있지 않음
- `studio` 본문이 비어 있지 않음
- 사이드바 active 상태가 본문과 일치

## 커밋/푸시 원칙

- Phase 단위로 커밋 1개씩
- 커밋 메시지는 가급적 `latest-review.md` 의 완료 신호 형식을 따를 것
- push 전 최소 확인:

```bash
git status -sb
python3 -m py_compile web_app.py
```

## 참고

- 현재 `최근작업정리.md` 는 이 핸드오프와 같이 최신 상태로 갱신됨
- 이 문서를 먼저 읽고, 그 다음 `design/notes/latest-review.md` 를 읽고 작업 시작하면 됨
