from __future__ import annotations

import argparse
import csv
import html
import threading
import urllib.parse
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import extract


@dataclass
class JobItem:
    url: str
    success: bool
    message: str


@dataclass
class AppState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    running: bool = False
    status: str = "대기 중"
    summary: str = "준비됨"
    total: int = 0
    completed: int = 0
    success_count: int = 0
    items: list[JobItem] = field(default_factory=list)
    notice: str = ""

    def snapshot(self) -> dict:
        with self.lock:
            return {
                "running": self.running,
                "status": self.status,
                "summary": self.summary,
                "total": self.total,
                "completed": self.completed,
                "success_count": self.success_count,
                "items": list(self.items),
                "notice": self.notice,
            }

    def set_notice(self, message: str) -> None:
        with self.lock:
            self.notice = message

    def start(self, total: int) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.status = "실행 중..."
            self.summary = f"준비 중 (0/{total})"
            self.total = total
            self.completed = 0
            self.success_count = 0
            self.items = []
            self.notice = ""
            return True

    def update_progress(self, index: int, total: int, url: str) -> None:
        with self.lock:
            self.status = f"분석 중... ({index}/{total})"
            self.summary = url

    def add_result(self, url: str, success: bool, message: str) -> None:
        with self.lock:
            self.completed += 1
            if success:
                self.success_count += 1
            self.items.append(JobItem(url=url, success=success, message=message))
            self.status = f"실행 중... ({self.completed}/{self.total})"
            self.summary = message

    def finish(self) -> None:
        with self.lock:
            self.running = False
            self.status = f"완료 ({self.success_count}/{self.total})"
            self.summary = "작업이 끝났습니다."


STATE = AppState()


def build_settings(form: dict[str, str]) -> tuple[dict, str]:
    config = extract.load_config()
    config.update(
        {
            "google_sheet_id": form.get("google_sheet_id", "").strip(),
            "worksheet": form.get("worksheet", "").strip() or extract.DEFAULT_WORKSHEET,
        }
    )
    extract.save_config(config)

    key_message = ""
    gemini_key = form.get("gemini_api_key", "").strip()
    if gemini_key:
        key_message = "Gemini API Key 저장 실패"
        if extract.set_gemini_api_key(gemini_key):
            key_message = "Gemini API Key 저장 완료"
    return config, key_message


def read_results_table(config: dict) -> list[dict[str, str]]:
    csv_path = extract.csv_path_for(config)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized: list[dict[str, str]] = []
    for row in rows:
        normalized.append(
            {
                "카메라 워킹": row.get("카메라 워킹", "").strip(),
                "프롬프트(영문)": row.get("프롬프트(영문)", "").strip(),
                "내용": (row.get("내용") or row.get("한줄번역") or "").strip(),
                "링크": row.get("링크", "").strip(),
            }
        )
    return normalized


def normalize_urls(raw_text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for line in raw_text.splitlines():
        url = line.strip()
        if not url or url in seen:
            continue
        urls.append(url)
        seen.add(url)
    return urls


def run_worker(urls: list[str]) -> None:
    try:
        total = len(urls)
        for index, url in enumerate(urls, start=1):
            STATE.update_progress(index, total, url)
            try:
                result = extract.run_pipeline(url)
                ok = bool(result.get("success"))
                usage = result.get("gemini_usage") or {}
                cost_text = ""
                if usage.get("krw_estimate"):
                    cost_text = f" (약 {usage['krw_estimate']:.0f}원)"
                message = result.get("sheet_status") or result.get("error") or "추출 완료"
                if ok and result.get("camera"):
                    message = f"추출 완료 · {result['camera']}{cost_text}"
                elif ok:
                    message = f"추출 완료{cost_text}"
                elif cost_text:
                    message = f"{message}{cost_text}"
            except Exception as exc:  # noqa: BLE001
                ok = False
                message = f"예외 발생: {exc}"
            STATE.add_result(url, ok, message)
    finally:
        STATE.finish()


class PromptExtractorHandler(BaseHTTPRequestHandler):
    server_version = "PromptExtractorWeb/2.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            self.render_home()
            return
        if parsed.path == "/download/csv":
            self.serve_file(extract.csv_path_for(extract.load_config()), "text/csv; charset=utf-8")
            return
        if parsed.path == "/download/xlsx":
            self.serve_file(
                extract.xlsx_path_for(extract.load_config()),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
            return
        if parsed.path == "/ping":
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        form = {key: values[-1] for key, values in urllib.parse.parse_qs(body, keep_blank_values=True).items()}

        if parsed.path == "/settings":
            _, key_message = build_settings(form)
            message = "설정을 저장했습니다."
            if key_message:
                message = f"{message} {key_message}"
            STATE.set_notice(message)
            self.redirect("/")
            return

        if parsed.path == "/run":
            urls = normalize_urls(form.get("urls", ""))
            if not urls:
                STATE.set_notice("링크를 한 줄에 하나씩 입력해 주세요.")
                self.redirect("/")
                return
            if not STATE.start(len(urls)):
                STATE.set_notice("이미 작업이 실행 중입니다. 현재 작업이 끝난 뒤 다시 시도해 주세요.")
                self.redirect("/")
                return
            thread = threading.Thread(target=run_worker, args=(urls,), daemon=True)
            thread.start()
            self.redirect("/")
            return

        if parsed.path == "/delete":
            url = form.get("url", "").strip()
            if not url:
                STATE.set_notice("삭제할 링크가 없습니다.")
                self.redirect("/")
                return
            result = extract.delete_result_by_url(url)
            STATE.set_notice(result.get("sheet_status") or "삭제 완료")
            self.redirect("/")
            return

        if parsed.path == "/clear":
            result = extract.clear_all_results()
            STATE.set_notice(result.get("sheet_status") or "전체 삭제 완료")
            self.redirect("/")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def render_home(self) -> None:
        snapshot = STATE.snapshot()
        config = extract.load_config()
        results = [row for row in read_results_table(config) if row.get("링크")]
        sheet_id = str(config.get("google_sheet_id", "")).strip()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""
        auto_refresh = '<meta http-equiv="refresh" content="2">' if snapshot["running"] else ""
        notice_html = f'<div class="notice">{self._escape(snapshot["notice"])}</div>' if snapshot["notice"] else ""

        recent_results = list(reversed(results[-80:]))
        camera_values: list[str] = []
        seen_camera: set[str] = set()
        for row in recent_results:
            for part in row.get("카메라 워킹", "").split("/"):
                camera = " ".join(part.split()).strip()
                if camera and camera not in seen_camera:
                    seen_camera.add(camera)
                    camera_values.append(camera)

        camera_filter_html = "".join(
            f'<label class="camera-chip"><input type="checkbox" value="{self._escape_attr(camera)}"><span>{self._escape(camera)}</span></label>'
            for camera in camera_values
        ) or '<div class="muted small">아직 필터할 카메라 워킹 데이터가 없습니다.</div>'

        rows_html = "".join(self._render_row(row) for row in recent_results)
        if not rows_html:
            rows_html = '<tr><td colspan="4" class="empty">아직 저장된 결과가 없습니다.</td></tr>'

        item_html = "".join(
            f'<li class="{"ok" if item.success else "fail"}"><strong>{self._escape(item.url)}</strong><span>{self._escape(item.message)}</span></li>'
            for item in snapshot["items"][-10:]
        ) or '<li class="empty">최근 작업 내역이 없습니다.</li>'

        gemini_ready = "설정됨" if extract.has_gemini_api_key() else "미설정"
        settings_open = " open" if not sheet_id else ""

        style = """
:root {
  color-scheme: light;
  --bg: #f5f3ee;
  --panel: #fffdf9;
  --ink: #203127;
  --muted: #647166;
  --line: #d9d5c9;
  --accent: #335c4a;
  --accent-soft: #e5f0ea;
  --chip: #edf3ee;
  --chip-on: #335c4a;
  --danger: #a33d33;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
  color: var(--ink);
  background: linear-gradient(180deg, #f7f2ea 0%, #eff3ee 100%);
}
main { max-width: 1280px; margin: 0 auto; padding: 28px 20px 56px; }
h1 { margin: 0 0 8px; font-size: 34px; }
p.lead { margin: 0 0 20px; color: var(--muted); font-size: 16px; }
.grid { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(320px, 0.85fr); gap: 18px; align-items: start; }
.panel {
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 22px;
  padding: 18px;
  box-shadow: 0 16px 36px rgba(45, 61, 50, 0.07);
}
.panel h2 { margin: 0 0 14px; font-size: 20px; }
.notice {
  margin-bottom: 16px;
  padding: 12px 14px;
  border-radius: 14px;
  background: #eef6f1;
  border: 1px solid #cfe0d6;
  color: var(--accent);
}
label { display: block; margin: 0 0 8px; font-size: 14px; color: var(--muted); }
textarea, input {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px;
  background: white;
  color: var(--ink);
  font: inherit;
}
textarea { min-height: 260px; resize: vertical; }
.actions, .links { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
button, .button-link {
  appearance: none;
  border: 0;
  border-radius: 12px;
  background: var(--accent);
  color: white;
  padding: 11px 16px;
  font: inherit;
  cursor: pointer;
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
button.secondary, .button-link.secondary {
  background: #dde8e1;
  color: var(--ink);
}
button.ghost {
  background: transparent;
  color: var(--accent);
  border: 1px solid #bfd0c4;
}
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.kpi {
  border: 1px solid var(--line);
  border-radius: 16px;
  padding: 14px;
  background: white;
}
.kpi .label { display: block; color: var(--muted); font-size: 13px; margin-bottom: 6px; }
.kpi strong { font-size: 20px; }
.activity {
  list-style: none;
  padding: 0;
  margin: 14px 0 0;
  display: grid;
  gap: 10px;
  max-height: 300px;
  overflow: auto;
}
.activity li {
  border: 1px solid var(--line);
  border-radius: 14px;
  padding: 12px 14px;
  background: white;
  display: grid;
  gap: 4px;
}
.activity li.ok { border-color: #cde2d4; }
.activity li.fail { border-color: #ecc6c1; }
.activity li strong { font-size: 13px; word-break: break-all; }
.activity li span { color: var(--muted); font-size: 13px; }
.settings-shell {
  margin-top: 14px;
  border: 1px solid var(--line);
  border-radius: 18px;
  overflow: hidden;
  background: white;
}
.settings-shell summary {
  list-style: none;
  cursor: pointer;
  padding: 14px 16px;
  font-weight: 700;
  color: var(--accent);
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.settings-shell summary::-webkit-details-marker { display: none; }
.settings-body { padding: 0 16px 16px; border-top: 1px solid #ece8de; }
.helper { color: var(--muted); font-size: 13px; margin: 10px 0 0; }
.results-panel { margin-top: 18px; }
.filters {
  position: sticky;
  top: 0;
  z-index: 5;
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 18px;
  background: rgba(255, 253, 249, 0.95);
  backdrop-filter: blur(10px);
}
.filters-head {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}
.filters-head strong { font-size: 16px; }
.filters-head .muted { font-size: 13px; color: var(--muted); }
.camera-filters { display: flex; gap: 8px; flex-wrap: wrap; }
.camera-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 11px;
  border-radius: 999px;
  background: var(--chip);
  border: 1px solid #d5e1d8;
  cursor: pointer;
  color: var(--accent);
  font-size: 13px;
}
.camera-chip input { display: none; }
.camera-chip.active { background: var(--chip-on); color: white; border-color: var(--chip-on); }
.table-shell {
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: 20px;
  background: white;
}
table { width: 100%; border-collapse: collapse; table-layout: fixed; }
thead th {
  background: #edf5ef;
  color: var(--accent);
  text-align: left;
  font-size: 15px;
  padding: 16px;
  border-bottom: 1px solid var(--line);
}
tbody td {
  vertical-align: top;
  padding: 16px;
  border-bottom: 1px solid #ece7de;
}
tbody tr:last-child td { border-bottom: 0; }
.col-camera { width: 18%; }
.col-prompt { width: 46%; }
.col-content { width: 22%; }
.col-link { width: 14%; }
.camera-tags { display: flex; flex-wrap: wrap; gap: 8px; }
.camera-tag {
  display: inline-flex;
  align-items: center;
  border: 0;
  background: var(--accent-soft);
  color: var(--accent);
  border-radius: 999px;
  padding: 7px 11px;
  font-size: 13px;
  cursor: pointer;
}
.prompt-preview {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: normal;
  word-break: break-word;
  line-height: 1.65;
}
.prompt-cell.expanded .prompt-preview {
  display: block;
  -webkit-line-clamp: unset;
  overflow: visible;
}
.prompt-more { margin-top: 10px; }
.prompt-more button {
  padding: 0;
  background: none;
  color: var(--accent);
  border: 0;
  font-size: 13px;
  cursor: pointer;
}
.content-cell { word-break: keep-all; line-height: 1.6; }
.link-cell a { color: #3459d7; text-decoration: underline; word-break: break-all; }
.empty { color: var(--muted); text-align: center; padding: 36px 16px; }
.small { font-size: 12px; }
.muted { color: var(--muted); }
.hidden-row { display: none; }
@media (max-width: 980px) {
  .grid { grid-template-columns: 1fr; }
  .col-camera { width: 28%; }
  .col-prompt { width: 40%; }
  .col-content { width: 20%; }
  .col-link { width: 12%; }
.col-manage { width: 10%; }
.manage-cell { white-space: nowrap; }
.small-delete { padding: 8px 12px; font-size: 12px; }
}
@media (max-width: 720px) {
  main { padding: 18px 14px 40px; }
  .panel { padding: 15px; border-radius: 18px; }
  .table-shell { overflow-x: auto; }
  table { min-width: 920px; }
}
"""

        script = """
const SYNONYM_GROUPS = [
  ['시간 정지','시간정지','시간스탑','타임스탑','time stop','time-stop','time freeze','time-freeze','타임 프리즈','타임프리즈'],
  ['술집','바','레스토랑','식당','restaurant','bar','pub'],
  ['맥주','술','beer','beers'],
  ['달리','도리','dolly','dolly in','dolly out'],
  ['스테디캠','steadicam'],
  ['트래킹','tracking','tracking shot'],
  ['클로즈업','close-up','close up'],
  ['광각','와이드','wide shot'],
  ['줌인','zoom in'],
  ['줌아웃','zoom out'],
  ['틸트업','tilt up'],
  ['틸트다운','tilt down'],
  ['드론','drone'],
  ['괴물','몬스터','monster'],
  ['전투','대치','fight','battle'],
  ['빗방울','빗물','raindrop','rain drop'],
  ['호텔','hotel'],
  ['유리병','bottle','glass bottle'],
  ['충격파','shockwave'],
  ['비둘기','pigeon','pigeons'],
  ['자동차','차','car'],
];

const searchInput = document.getElementById('content-search');
const cameraInputs = Array.from(document.querySelectorAll('.camera-chip input'));
const chips = Array.from(document.querySelectorAll('.camera-chip'));
const rows = Array.from(document.querySelectorAll('tbody tr[data-search]'));
const countLabel = document.getElementById('result-count');
const resetButton = document.getElementById('reset-filters');

function normalizeText(value) {
  return (value || '').toLowerCase().replace(/[\\s_\\-\\/]+/g, ' ').trim();
}

function expandToken(token) {
  const normalized = normalizeText(token);
  if (!normalized) return [];
  const expanded = new Set([normalized]);
  for (const group of SYNONYM_GROUPS) {
    if (group.some(item => normalizeText(item) === normalized || normalizeText(item).includes(normalized) || normalized.includes(normalizeText(item)))) {
      group.forEach(item => expanded.add(normalizeText(item)));
    }
  }
  return Array.from(expanded);
}

function syncChipState() {
  chips.forEach(chip => {
    const input = chip.querySelector('input');
    chip.classList.toggle('active', !!input.checked);
  });
}

function applyFilters() {
  const rawQuery = searchInput ? searchInput.value.trim() : '';
  const terms = rawQuery ? rawQuery.split(/\\s+/).filter(Boolean) : [];
  const selectedCameras = cameraInputs.filter(input => input.checked).map(input => input.value);
  let visible = 0;

  rows.forEach(row => {
    const searchText = normalizeText(row.dataset.search || '');
    const rowCameras = (row.dataset.camera || '').split('|').map(normalizeText).filter(Boolean);
    const queryMatch = terms.every(term => {
      const expandedTerms = expandToken(term);
      return expandedTerms.some(item => searchText.includes(item));
    });
    const cameraMatch = selectedCameras.every(camera => rowCameras.includes(normalizeText(camera)));
    const show = queryMatch && cameraMatch;
    row.classList.toggle('hidden-row', !show);
    if (show) visible += 1;
  });

  if (countLabel) {
    countLabel.textContent = `표시 ${visible}건`;
  }
}

if (searchInput) {
  searchInput.addEventListener('input', applyFilters);
}

cameraInputs.forEach(input => {
  input.addEventListener('change', () => {
    syncChipState();
    applyFilters();
  });
});

chips.forEach(chip => {
  chip.addEventListener('click', event => {
    if (event.target.tagName.toLowerCase() === 'input') return;
    const input = chip.querySelector('input');
    input.checked = !input.checked;
    syncChipState();
    applyFilters();
  });
});

Array.from(document.querySelectorAll('.camera-tag')).forEach(button => {
  button.addEventListener('click', () => {
    const target = normalizeText(button.dataset.camera || '');
    cameraInputs.forEach(input => {
      input.checked = normalizeText(input.value) === target;
    });
    syncChipState();
    applyFilters();
    if (searchInput) searchInput.scrollIntoView({ behavior: 'smooth', block: 'center' });
  });
});

Array.from(document.querySelectorAll('.toggle-prompt')).forEach(button => {
  button.addEventListener('click', () => {
    const cell = button.closest('.prompt-cell');
    const expanded = cell.classList.toggle('expanded');
    button.textContent = expanded ? '접기' : '더 보기';
  });
});

if (resetButton) {
  resetButton.addEventListener('click', () => {
    if (searchInput) searchInput.value = '';
    cameraInputs.forEach(input => { input.checked = false; });
    syncChipState();
    applyFilters();
  });
}

syncChipState();
applyFilters();
"""

        page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{auto_refresh}
<title>프롬프트 추출기</title>
<style>{style}</style>
</head>
<body>
<main>
  {notice_html}
  <h1>프롬프트 추출기</h1>
  <p class="lead">링크를 넣으면 영상을 임시 다운로드한 뒤 Gemini가 직접 분석하고, 결과는 Google Sheets와 최근 결과 표에 반영됩니다.</p>

  <section class="grid">
    <div class="panel">
      <h2>실행</h2>
      <form method="post" action="/run">
        <label for="urls">링크 입력</label>
        <textarea id="urls" name="urls" placeholder="https://www.instagram.com/reel/..."></textarea>
        <div class="actions">
          <button type="submit" {'disabled' if snapshot['running'] else ''}>전체 추출</button>
          <button type="button" class="secondary" onclick="document.getElementById('urls').value='https://www.instagram.com/reel/DXGdtNtEwhu/?utm_source=ig_web_copy_link&igsh=MzRlODBiNWFlZA=='">예시 링크 넣기</button>
        </div>
        <p class="helper">영상과 프레임은 서버에 남기지 않고 임시 처리 후 삭제합니다. CSV/XLSX는 필요할 때만 브라우저에서 다운로드하면 됩니다.</p>
      </form>

      <details class="settings-shell"{settings_open}>
        <summary><span>설정</span><span class="small muted">시트 연동과 Gemini 키만 관리합니다</span></summary>
        <div class="settings-body">
          <form method="post" action="/settings">
            <label for="google_sheet_id">Google Sheet ID</label>
            <input id="google_sheet_id" name="google_sheet_id" value="{self._escape_attr(sheet_id)}" placeholder="1DtWPwJCLsz3BkKaspfCqNpT5844hd7r736vfwPGY1bA">
            <label for="worksheet">워크시트 이름</label>
            <input id="worksheet" name="worksheet" value="{self._escape_attr(str(config.get('worksheet', extract.DEFAULT_WORKSHEET)))}">
            <label for="gemini_api_key">Gemini API Key</label>
            <input id="gemini_api_key" name="gemini_api_key" type="password" placeholder="새 키를 저장할 때만 입력하세요">
            <p class="helper">Gemini 키 상태: <strong>{gemini_ready}</strong>. 키를 새로 바꿀 때만 다시 입력하면 됩니다.</p>
            <div class="actions">
              <button type="submit">설정 저장</button>
              {('<a class="button-link secondary" href="' + self._escape_attr(sheet_url) + '" target="_blank">Google Sheet 열기</a>') if sheet_url else ''}
            </div>
          </form>
        </div>
      </details>
    </div>

    <aside class="panel">
      <h2>진행 상태</h2>
      <div class="kpis">
        <div class="kpi"><span class="label">상태</span><strong>{self._escape(snapshot['status'])}</strong></div>
        <div class="kpi"><span class="label">성공</span><strong>{snapshot['success_count']}</strong></div>
        <div class="kpi"><span class="label">전체</span><strong>{snapshot['total']}</strong></div>
      </div>
      <p class="helper">{self._escape(snapshot['summary'])}</p>
      <div class="links">
        <a class="button-link secondary" href="/download/csv">CSV 다운로드</a>
        <a class="button-link secondary" href="/download/xlsx">XLSX 다운로드</a>
        {('<a class="button-link ghost" href="' + self._escape_attr(sheet_url) + '" target="_blank">시트 보기</a>') if sheet_url else ''}
      </div>
      <ul class="activity">{item_html}</ul>
    </aside>
  </section>

  <section class="panel results-panel">
    <h2>최근 결과</h2>
    <div class="filters">
      <div class="filters-head">
        <div>
          <strong>통합 검색</strong>
          <div class="muted">내용, 카메라 워킹, 프롬프트 본문을 동시에 검색합니다. 한글과 영어 키워드는 유사어로 함께 찾습니다.</div>
        </div>
        <div class="muted" id="result-count">표시 {len(recent_results)}건</div>
      </div>
      <input id="content-search" type="search" placeholder="예: 시간 정지, 술집, dolly, steadicam, 괴물 전투">
      <div id="camera-filters" class="camera-filters">{camera_filter_html}</div>
      <div class="actions" style="margin-top:0"><button type="button" class="ghost" id="reset-filters">필터 초기화</button><form method="post" action="/clear" onsubmit="return confirm('최근 결과 전체를 삭제하시겠습니까? 시트에서도 함께 삭제됩니다.')"><button type="submit" class="ghost">전체 삭제</button></form></div>
    </div>

    <div class="table-shell">
      <table>
        <thead>
          <tr>
            <th class="col-camera">카메라 워킹</th>
            <th class="col-prompt">프롬프트(영문)</th>
            <th class="col-content">내용</th>
            <th class="col-link">링크</th>
            <th class="col-manage">관리</th>
          </tr>
        </thead>
        <tbody>
          {rows_html}
        </tbody>
      </table>
    </div>
  </section>
</main>
<script>{script}</script>
</body>
</html>
"""

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(page.encode("utf-8"))

    def serve_file(self, path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.wfile.write(path.read_bytes())

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, fmt: str, *args) -> None:
        return

    @staticmethod
    def _escape(value: str) -> str:
        return html.escape(value or "")

    @staticmethod
    def _escape_attr(value: str) -> str:
        return html.escape(value or "", quote=True)

    def _render_row(self, row: dict[str, str]) -> str:
        prompt = row.get("프롬프트(영문)", "")
        content = row.get("내용", "")
        link = row.get("링크", "")
        cameras = [" ".join(part.split()).strip() for part in row.get("카메라 워킹", "").split("/") if part.strip()]
        camera_tags = "".join(
            f'<button type="button" class="camera-tag" data-camera="{self._escape_attr(camera)}">{self._escape(camera)}</button>'
            for camera in cameras
        ) or '<span class="muted small">미분류</span>'
        search_parts = [prompt, content, link, " ".join(cameras)]
        data_search = self._escape_attr(" ".join(part for part in search_parts if part))
        data_camera = self._escape_attr("|".join(cameras))
        prompt_html = self._escape(prompt).replace("\n", "<br>")
        content_html = self._escape(content)
        link_html = f'<a href="{self._escape_attr(link)}" target="_blank">열기</a>' if link else '<span class="muted small">링크 없음</span>'
        delete_html = (
            f'<form method="post" action="/delete" onsubmit="return confirm(&quot;이 항목을 삭제하시겠습니까? 시트에서도 함께 삭제됩니다.&quot;)">'
            f'<input type="hidden" name="url" value="{self._escape_attr(link)}">'
            f'<button type="submit" class="ghost small-delete">삭제</button>'
            f'</form>'
        ) if link else '<span class="muted small">-</span>'
        return (
            f'<tr data-search="{data_search}" data-camera="{data_camera}">'
            f'<td><div class="camera-tags">{camera_tags}</div></td>'
            f'<td class="prompt-cell"><div class="prompt-preview">{prompt_html}</div><div class="prompt-more"><button type="button" class="toggle-prompt">더 보기</button></div></td>'
            f'<td class="content-cell">{content_html}</td>'
            f'<td class="link-cell">{link_html}</td>'
            f'<td class="manage-cell">{delete_html}</td>'
            f'</tr>'
        )


def run_server(host: str, port: int, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), PromptExtractorHandler)
    url = f"http://{host}:{port}" if host != "0.0.0.0" else f"http://127.0.0.1:{port}"
    print(f"PromptExtractor 웹 서버 실행 중: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="PromptExtractor web server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=int(__import__('os').environ.get('PORT', '5001')))
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, open_browser=args.open_browser)


if __name__ == "__main__":
    main()
