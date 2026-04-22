# Grommy G 배포 가이드

이 프로젝트는 이제 웹앱으로 배포할 수 있습니다.

## 추천 운영 방식
- 외부에서 모바일로 접속하려면, 항상 켜져 있는 서버 1대에 올립니다.
- 서버는 Gemini API Key와 Google Sheets credentials만 갖고, 사용자는 브라우저로만 접속합니다.
- URL 한 개로 PC/모바일에서 공용 사용합니다.

## 배포 전 준비
1. `GEMINI_API_KEY` 준비
2. Google service account JSON 준비
3. Google Sheet ID 확인

## 환경변수
아래 값들을 서버에 설정하면 됩니다.

- `PORT`
- `PROMPT_EXTRACTOR_PUBLIC_URL` (선택, 고정 URL 명시용)
- `GEMINI_API_KEY`
- `PROMPT_EXTRACTOR_GOOGLE_SHEET_ID`
- `PROMPT_EXTRACTOR_WORKSHEET`
- `PROMPT_EXTRACTOR_OUTPUT_DIR`
- `PROMPT_EXTRACTOR_CREDENTIALS_PATH`
- `GOOGLE_CREDENTIALS_JSON`
- `PROMPT_EXTRACTOR_APP_DIR` (선택)

Render에서는 아래 기본값을 권장합니다.
- `PROMPT_EXTRACTOR_APP_DIR=/tmp/prompt-extractor-app`
- `PROMPT_EXTRACTOR_OUTPUT_DIR=/tmp/prompt-extractor-data`
- `PROMPT_EXTRACTOR_PUBLIC_URL=https://your-service.onrender.com`

이 프로젝트는 Google Sheets를 메인 저장소로 사용하는 구조라, Render 컨테이너의 임시 파일 시스템을 써도 운영이 가능합니다.

`GOOGLE_CREDENTIALS_JSON`을 넣으면 서버 시작 시 운영체제별 앱 데이터 폴더의 `credentials.json`에 자동으로 써집니다.

기본 앱 데이터 폴더:
- macOS: `~/Library/Application Support/PromptExtractor`
- Windows: `%APPDATA%\\PromptExtractor`
- Linux: `~/.config/PromptExtractor`

`PROMPT_EXTRACTOR_APP_DIR`를 주면 이 기본 경로 대신 원하는 위치를 강제로 사용할 수 있습니다.

## Docker 실행 예시
```bash
docker build -t prompt-extractor .
docker run -d \
  -p 5001:5001 \
  -e GEMINI_API_KEY=... \
  -e PROMPT_EXTRACTOR_GOOGLE_SHEET_ID=... \
  -e PROMPT_EXTRACTOR_WORKSHEET=Sheet1 \
  -e GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}' \
  -e PROMPT_EXTRACTOR_OUTPUT_DIR=/data/prompt-extractor \
  --name prompt-extractor \
  prompt-extractor
```

## 내부 서버 배포
사내 서버나 클라우드 VM에서 아래처럼 실행해도 됩니다.
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...
export PROMPT_EXTRACTOR_GOOGLE_SHEET_ID=...
export PROMPT_EXTRACTOR_WORKSHEET=Sheet1
export GOOGLE_CREDENTIALS_JSON='{"type":"service_account",...}'
python3 app.py --host 0.0.0.0 --port 5001
```

## 외부 접속
- 내부 테스트: `http://서버IP:5001`
- 외부 접속: 회사 도메인, reverse proxy, HTTPS 연결 권장
- 모바일에서 쓰려면 HTTPS가 가장 안정적입니다.

## 배포 상태 확인
배포 후 아래 주소들로 상태를 바로 확인할 수 있습니다.

- `/ping` : 헬스체크
- `/api/state` : 현재 작업 상태/세션 요약
- `/api/library` : 최근 아카이브 요약
- `/api/deployment` : 배포 준비 상태, 공개 URL, 출력 경로, Sheets/Gemini 준비 여부

## 결과 저장
- 결과 CSV/XLSX: `PROMPT_EXTRACTOR_OUTPUT_DIR/outputs`
- 링크 실행 시 영상/프레임은 임시 폴더에서만 처리되고, 작업 후 자동 삭제됩니다.
- Google Sheets는 자동 업데이트됩니다.

## 코드 동기화

배포 서버와 개발용 PC/맥북의 코드는 Git 원격 저장소로 관리하는 것을 권장합니다.

추천 순서:
1. 로컬 저장소를 GitHub private repo에 push
2. 배포 서버에서는 그 저장소를 clone
3. 집/회사/윈도우 환경에서는 같은 저장소를 pull 해서 작업

민감 정보는 Git에 올리지 않습니다.
- `credentials.json`
- API 키
- `config.json`
- `secrets.json`
- 로컬 결과물
