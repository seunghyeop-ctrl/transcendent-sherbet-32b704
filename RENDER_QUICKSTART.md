# Grommy G Render 빠른 배포 가이드

이 문서는 현재 프로젝트를 **Render 웹 서비스**로 배포하는 가장 짧은 절차만 정리한 문서입니다.

## 1. GitHub 첫 push

이 프로젝트는 이미 Git remote가 연결돼 있습니다.

```bash
cd "/Users/seunghyeop/Documents/Claude/Projects/프롬프트 추출 및 분류 작성 자동화 프로그램 개발"
git push -u origin main
```

GitHub 인증이 필요하면:
- Username: `seunghyeop-ctrl`
- Password 자리에는 **GitHub Personal Access Token(PAT)** 입력

## 2. Render에서 새 Web Service 생성

1. Render 로그인
2. `New +` → `Web Service`
3. GitHub 저장소 연결
4. 저장소 선택:
   - `seunghyeop-ctrl/transcendent-sherbet-32b704`
5. 설정:
   - Runtime: `Docker`
   - Region: 가까운 곳 선택
   - Branch: `main`

이 프로젝트는 이미 `render.yaml`, `Dockerfile`, `deploy/start.sh`가 준비되어 있어서
별도 Start Command 없이도 배포할 수 있습니다.

## 3. Render 환경변수

Render 대시보드의 `Environment`에 아래 값을 넣습니다.

### 필수

- `GEMINI_API_KEY`
- `PROMPT_EXTRACTOR_GOOGLE_SHEET_ID`
- `PROMPT_EXTRACTOR_WORKSHEET`
- `GOOGLE_CREDENTIALS_JSON`
- `PROMPT_EXTRACTOR_PUBLIC_URL`

### 이미 기본값이 들어가도 되는 것

- `PORT=5001`
- `PROMPT_EXTRACTOR_APP_DIR=/tmp/prompt-extractor-app`
- `PROMPT_EXTRACTOR_OUTPUT_DIR=/tmp/prompt-extractor-data`
- `PROMPT_EXTRACTOR_PUBLIC_URL=https://your-render-service.onrender.com`

## 4. 값 형식 예시

### 워크시트 이름

```text
Sheet1
```

### Google Sheet ID

시트 URL:

```text
https://docs.google.com/spreadsheets/d/1DtWPwJCLsz3BkKaspfCqNpT5844hd7r736vfwPGY1bA/edit#gid=0
```

위 URL이면 ID는 아래입니다.

```text
1DtWPwJCLsz3BkKaspfCqNpT5844hd7r736vfwPGY1bA
```

### GOOGLE_CREDENTIALS_JSON

서비스 계정 JSON 파일 전체 내용을 **한 줄 JSON 문자열**로 넣으면 됩니다.

예:

```json
{"type":"service_account","project_id":"...","private_key_id":"...","private_key":"-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n","client_email":"...","client_id":"...","token_uri":"https://oauth2.googleapis.com/token"}
```

## 5. 배포 후 확인

Render가 배포를 끝내면 고정 URL이 생깁니다.

확인할 주소:
- `/ping`
- `/api/deployment`
- `/?view=run`
- `/?view=library`
- `/?view=settings`

예:

```text
https://your-render-service.onrender.com/ping
```

정상이라면 `ok` 가 나옵니다.

## 6. 이후 작업 흐름

처음 1회 배포 후에는 이렇게 씁니다.

### 집/회사/윈도우 어디서든

작업 시작 전:

```bash
git pull
```

작업 후:

```bash
git add .
git commit -m "작업 내용"
git push
```

Render는 `main` 브랜치 push를 감지하면 자동 배포합니다.
