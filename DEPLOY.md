# 프롬프트 추출기 배포 가이드

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
- `GEMINI_API_KEY`
- `PROMPT_EXTRACTOR_GOOGLE_SHEET_ID`
- `PROMPT_EXTRACTOR_WORKSHEET`
- `PROMPT_EXTRACTOR_OUTPUT_DIR`
- `PROMPT_EXTRACTOR_CREDENTIALS_PATH`
- `GOOGLE_CREDENTIALS_JSON`

`GOOGLE_CREDENTIALS_JSON`을 넣으면 서버 시작 시 `~/Library/Application Support/PromptExtractor/credentials.json`에 자동으로 써집니다.

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
python3 app.py --host 0.0.0.0 --port 5001 --no-browser
```

## 외부 접속
- 내부 테스트: `http://서버IP:5001`
- 외부 접속: 회사 도메인, reverse proxy, HTTPS 연결 권장
- 모바일에서 쓰려면 HTTPS가 가장 안정적입니다.

## 결과 저장
- 결과 CSV/XLSX: `PROMPT_EXTRACTOR_OUTPUT_DIR/outputs`
- 링크 실행 시 영상/프레임은 임시 폴더에서만 처리되고, 작업 후 자동 삭제됩니다.
- Google Sheets는 자동 업데이트됩니다.
