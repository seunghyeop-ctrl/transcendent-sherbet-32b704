# design/ — UI/UX 지시서 폴더

> Grommy 프로젝트의 **디자이너(Claude) ↔ 개발자(Codex) 인계 채널**.
> 코드가 아니라 **수정 지시서**가 들어가는 곳.

---

## 역할 분담

| 역할 | 담당 | 하는 일 |
|------|------|---------|
| PM / 컨트롤러 | 사람 | Phase 시작·완료 신호, Push/Pull 1클릭 |
| UX/UI 디자이너 | Claude | 라이브 사이트 분석 + 수정 지시서 작성 |
| 개발자 | Codex | 지시서대로 코드 수정 + 커밋 |
| 전달 매체 | GitHub | design/ 폴더 동기화 |

---

## 폴더 구조

```
design/
├── README.md                         ← 이 파일
└── notes/
    ├── latest-review.md              ← Codex는 이 파일 하나만 본다 (고정 경로)
    └── archive/
        ├── 2026-04-22-phase0-handoff.md
        ├── 2026-04-22-phase1-review.md
        └── ...
```

### `notes/latest-review.md`
- **Codex가 항상 읽는 유일한 파일.**
- Claude가 새 리뷰를 쓸 때마다 **이 파일을 덮어씀**.
- Codex 지시 문장 예: `"design/notes/latest-review.md 파일 먼저 읽고 그대로 수정해"`

### `notes/archive/YYYY-MM-DD-phaseN-review.md`
- Claude가 새 리뷰 쓸 때마다 **똑같은 내용을 여기에도 저장**.
- 과거 리뷰를 거슬러 올라가 확인할 수 있게 하는 히스토리 백업.
- Claude가 `latest-review.md`를 덮어쓰기 전에 반드시 `archive/`에 먼저 복사.

---

## 운영 흐름 (1 사이클)

```
1. 사람: "Phase N 시작"
2. 사람: Claude에게 현재 상태 리뷰 요청
   └─ "현재 배포된 사이트(https://grommy.onrender.com) 기준으로 UX 분석하고
       design/notes/latest-review.md 형식으로 작성해줘"
3. Claude: Chrome MCP로 라이브 사이트 확인 → archive/에 백업 → latest-review.md 작성 → 커밋
4. 사람: GitHub Desktop 열고 "Push origin" 1클릭
5. 사람: Codex에게 적용 요청
   └─ "repo의 design/notes/latest-review.md 파일 기준으로 UI 전면 수정 진행해"
6. Codex: 코드 수정 + 커밋 + push
7. Render 자동 재배포 → 사이트 확인
8. 사람: "Phase N 완료" → 1번으로 돌아가 다음 Phase 시작
```

---

## 금지 사항

- ❌ Claude에게 코드 직접 수정 시키기 (Claude는 지시서만 작성)
- ❌ Codex에게 UX 고민 맡기기 (Codex는 지시서대로 구현만)
- ❌ GitHub 거치지 않고 로컬 파일 복붙 공유 (추적 불가)
- ❌ `latest-review.md`를 archive 백업 없이 덮어쓰기

---

## 관련 파일

- 루트 `ui-mockup.html` — 최종 목표 UI (Archive/Studio 2+2 구조)
- 루트 `ui-mockup-v1.html` — 이전 목업(6뷰 버전) 백업
- 루트 `web_app.py` — 백엔드 (Codex가 Phase 1에서 라우팅 수정 중)
- 루트 `extract.py` — Gemini + 스프레드시트 파이프라인
