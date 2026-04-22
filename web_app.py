from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import threading
import urllib.parse
import webbrowser
from collections import Counter
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import extract


TEMPLATE_PATH = Path(__file__).with_name("ui-mockup.html")
VALID_VIEWS = {"dashboard", "run", "generate", "library", "settings", "about"}
PUBLIC_URL_ENV_KEYS = (
    "PROMPT_EXTRACTOR_PUBLIC_URL",
    "PUBLIC_URL",
    "RENDER_EXTERNAL_URL",
    "URL",
)
SEARCH_SYNONYM_GROUPS = [
    ["시간 정지", "시간정지", "시간스탑", "time-freeze", "time freeze", "time stop", "time-stop"],
    ["술집", "바", "레스토랑", "식당", "restaurant", "bar", "pub"],
    ["맥주", "술", "beer", "beers"],
    ["달리", "dolly", "dolly in", "dolly out"],
    ["스테디캠", "steadicam"],
    ["트래킹", "tracking", "tracking shot", "follow shot"],
    ["드론", "drone", "aerial"],
    ["괴물", "몬스터", "monster"],
    ["전투", "대치", "fight", "battle"],
    ["빗방울", "빗물", "raindrop", "rain drop", "rain"],
    ["호텔", "hotel"],
    ["유리병", "bottle", "glass bottle"],
    ["충격파", "shockwave"],
    ["비둘기", "pigeon", "pigeons"],
    ["자동차", "차", "car"],
]
DEFAULT_CHAT_GREETING = {
    "role": "ai",
    "text": "안녕하세요. 만들고 싶은 장면이나 시나리오를 적어주시면, 클라우드 아카이브의 실제 레퍼런스를 참고해 영어 프롬프트를 그루밍해드릴게요.",
    "prompt": "",
    "refs": [],
    "meta": "Gemini · 클라우드 아카이브 규칙 참조 활성",
    "summary": "",
    "camera_tags": [],
}


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
    chat_items: list[dict] = field(default_factory=list)

    def snapshot(self) -> dict:
        with self.lock:
            if not self.chat_items:
                self.chat_items = [DEFAULT_CHAT_GREETING.copy()]
            return {
                "running": self.running,
                "status": self.status,
                "summary": self.summary,
                "total": self.total,
                "completed": self.completed,
                "success_count": self.success_count,
                "items": list(self.items),
                "notice": self.notice,
                "chat_items": [dict(item) for item in self.chat_items],
            }

    def set_notice(self, message: str) -> None:
        with self.lock:
            self.notice = message

    def start(self, total: int) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = True
            self.status = "실행 중"
            self.summary = f"준비 중 (0/{total})"
            self.total = total
            self.completed = 0
            self.success_count = 0
            self.items = []
            self.notice = ""
            return True

    def update_progress(self, index: int, total: int, url: str) -> None:
        with self.lock:
            self.status = f"분석 중 ({index}/{total})"
            self.summary = url

    def add_result(self, url: str, success: bool, message: str) -> None:
        with self.lock:
            self.completed += 1
            if success:
                self.success_count += 1
            self.items.append(JobItem(url=url, success=success, message=message))
            self.status = f"실행 중 ({self.completed}/{self.total})"
            self.summary = message

    def set_runtime_message(self, status: str, summary: str) -> None:
        with self.lock:
            self.status = status
            self.summary = summary

    def finish(self) -> None:
        with self.lock:
            self.running = False
            self.status = f"완료 ({self.success_count}/{self.total})"
            self.summary = "작업이 끝났습니다."

    def add_chat_pair(
        self,
        user_text: str,
        ai_text: str,
        prompt: str = "",
        refs: list[dict] | None = None,
        meta: str = "",
        summary: str = "",
        camera_tags: list[str] | None = None,
    ) -> None:
        with self.lock:
            if not self.chat_items:
                self.chat_items = [DEFAULT_CHAT_GREETING.copy()]
            self.chat_items.append({"role": "user", "text": user_text, "prompt": "", "refs": [], "meta": ""})
            self.chat_items.append(
                {
                    "role": "ai",
                    "text": ai_text,
                    "prompt": prompt,
                    "refs": refs or [],
                    "meta": meta,
                    "summary": summary,
                    "camera_tags": camera_tags or [],
                }
            )

    def clear_chat(self) -> None:
        with self.lock:
            self.chat_items = [DEFAULT_CHAT_GREETING.copy()]

    def get_chat_item(self, index: int) -> dict | None:
        with self.lock:
            if 0 <= index < len(self.chat_items):
                return dict(self.chat_items[index])
        return None


STATE = AppState()


def normalize_match_text(value: str) -> str:
    return re.sub(r"[\s_\-/]+", " ", (value or "").lower()).strip()


def tokenize_text(value: str) -> list[str]:
    return [normalize_match_text(token) for token in re.findall(r"[가-힣A-Za-z0-9]+", value or "") if normalize_match_text(token)]


def expand_token(token: str) -> set[str]:
    normalized = normalize_match_text(token)
    if not normalized:
        return set()
    expanded = {normalized}
    for group in SEARCH_SYNONYM_GROUPS:
        normalized_group = [normalize_match_text(item) for item in group]
        if any(item == normalized or item in normalized or normalized in item for item in normalized_group):
            expanded.update(normalized_group)
    return expanded


def score_reference_row(query: str, row: dict[str, str]) -> int:
    haystack = normalize_match_text(" ".join([row.get("내용", ""), row.get("카메라 워킹", ""), row.get("프롬프트(영문)", "")]))
    if not haystack:
        return 0
    score = 0
    for token in tokenize_text(query):
        expanded = expand_token(token)
        if any(candidate and candidate in haystack for candidate in expanded):
            score += 3
    for camera in parse_camera_parts(row.get("카메라 워킹", "")):
        if normalize_match_text(camera) in haystack:
            score += 1
    if row.get("내용") and normalize_match_text(row["내용"]) in haystack:
        score += 1
    return score


def select_reference_rows(query: str, rows: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    scored = []
    for row in rows:
        score = score_reference_row(query, row)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda item: item[0], reverse=True)
    picked = [row for _, row in scored[:limit]]
    if picked:
        return picked
    return rows[:limit]


def merge_reference_rows(primary: list[dict[str, str]], secondary: list[dict[str, str]], limit: int = 5) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in primary + secondary:
        normalized = normalize_result_row(row)
        key = normalized.get("링크", "") or f"{normalized.get('내용','')}|{normalized.get('프롬프트(영문)','')[:120]}"
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged


def build_archive_groom_prompt(user_text: str, refs: list[dict[str, str]]) -> str:
    ref_lines = []
    for index, row in enumerate(refs, start=1):
        ref_lines.append(
            f"[{index}] 내용: {row.get('내용','')}\n"
            f"카메라: {row.get('카메라 워킹','')}\n"
            f"프롬프트: {row.get('프롬프트(영문)','')[:1200]}"
        )
    refs_blob = "\n\n".join(ref_lines) if ref_lines else "참고 레퍼런스 없음"
    return f"""
You are Grommy, an AI prompt groomer for cinematic prompt design.

User scenario:
{user_text}

Reference archive:
{refs_blob}

Rules:
- Return polished output based on the user's scenario and the reference archive.
- Keep the English prompt practical, vivid, and production-ready.
- Mention camera movement suggestions based on the references.
- Do not mention internal analysis or safety commentary.
- Reply only as JSON.

JSON schema:
{{
  "reply_ko": "short Korean explanation of how you groomed the result",
  "summary_ko": "very short Korean archive title for this prompt",
  "prompt_en": "final polished English prompt",
  "camera_tags": ["tag1", "tag2"],
  "reference_indexes": [1, 2]
}}
""".strip()


def call_gemini_groom_prompt(user_text: str, refs: list[dict[str, str]]) -> tuple[dict, str, dict]:
    api_key = extract.get_gemini_api_key().strip()
    if not api_key:
        return {}, "Gemini API 키가 설정되지 않았습니다.", extract.estimate_gemini_cost("gemini-2.5-flash", 0, 0)
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return {}, "google-genai 라이브러리가 설치되어 있지 않습니다.", extract.estimate_gemini_cost("gemini-2.5-flash", 0, 0)

    client = genai.Client(api_key=api_key)
    last_error = ""
    last_usage = extract.estimate_gemini_cost("gemini-2.5-flash", 0, 0)
    prompt = build_archive_groom_prompt(user_text, refs)
    for model_name in extract.MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.3),
            )
            last_usage = extract.extract_usage_metadata(response, model_name)
            text = (response.text or "").strip()
            if text:
                return json.loads(text), "", last_usage
        except Exception as exc:  # noqa: BLE001
            last_error = f"{model_name}: {exc}"
    return {}, last_error or "응답 없음", last_usage


def fallback_groom_response(user_text: str, refs: list[dict[str, str]]) -> tuple[dict, dict]:
    camera_tags: list[str] = []
    for row in refs:
        for camera in parse_camera_parts(row.get("카메라 워킹", "")):
            if camera not in camera_tags:
                camera_tags.append(camera)
    prompt_bits = [user_text.strip()]
    if refs:
        prompt_bits.append("Inspired by reference shots with " + ", ".join(camera_tags[:3] or ["cinematic camera movement"]))
        prompt_bits.append(refs[0].get("프롬프트(영문)", "")[:800])
    return (
        {
            "reply_ko": "Gemini 응답이 불안정해 아카이브 기반 초안으로 먼저 그루밍했습니다.",
            "summary_ko": refs[0].get("내용", "") if refs else user_text[:28],
            "prompt_en": "\n".join(part for part in prompt_bits if part).strip(),
            "camera_tags": camera_tags[:4],
            "reference_indexes": list(range(1, min(len(refs), 3) + 1)),
        },
        extract.estimate_gemini_cost("gemini-2.5-flash", 0, 0),
    )


def parse_camera_parts(value: str) -> list[str]:
    return [" ".join(part.split()).strip() for part in (value or "").split("/") if part.strip()]


def detect_source_code(url: str) -> str:
    text = (url or "").lower()
    if text.startswith("grommy://generated/"):
        return "AI"
    if "instagram.com" in text:
        return "IG"
    if "youtube.com" in text or "youtu.be" in text:
        return "YT"
    return "WEB"


def parse_cost_from_message(message: str) -> float:
    match = re.search(r"약\s*([\d,.]+)원", message or "")
    if not match:
        return 0.0
    return float(match.group(1).replace(",", ""))


def validate_gemini_api_key(candidate_key: str) -> tuple[bool, str]:
    api_key = (candidate_key or "").strip()
    if not api_key:
        return False, "Gemini API Key가 비어 있습니다."
    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return False, "google-genai 라이브러리가 설치되어 있지 않습니다."

    client = genai.Client(api_key=api_key)
    last_error = ""
    for model_name in extract.MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=["Return exactly OK."],
                config=types.GenerateContentConfig(temperature=0),
            )
            if (response.text or "").strip():
                return True, f"Gemini API Key 저장 및 검증 완료 ({model_name})"
        except Exception as exc:  # noqa: BLE001
            last_error = f"{model_name}: {exc}"
    return False, f"Gemini API Key 검증 실패 · {last_error or '응답 없음'}"


def build_settings(form: dict[str, str]) -> tuple[dict, str]:
    config = extract.load_config()
    updates: dict[str, str] = {}
    if "google_sheet_id" in form:
        updates["google_sheet_id"] = form.get("google_sheet_id", "").strip()
    if "worksheet" in form:
        updates["worksheet"] = form.get("worksheet", "").strip() or extract.DEFAULT_WORKSHEET
    if updates:
        config.update(updates)
    config = extract.save_config(config)

    key_message = ""
    gemini_key = form.get("gemini_api_key", "").strip()
    if gemini_key:
        valid, validation_message = validate_gemini_api_key(gemini_key)
        if valid and extract.set_gemini_api_key(gemini_key):
            key_message = validation_message
        elif valid:
            key_message = "Gemini API Key 검증은 통과했지만 Keychain 저장에 실패했습니다."
        else:
            key_message = validation_message
    return config, key_message


def get_public_base_url(handler: BaseHTTPRequestHandler | None = None) -> str:
    for env_name in PUBLIC_URL_ENV_KEYS:
        value = os.getenv(env_name, "").strip()
        if value:
            return value.rstrip("/")

    render_hostname = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
    if render_hostname:
        return f"https://{render_hostname}".rstrip("/")

    if handler:
        forwarded_proto = handler.headers.get("X-Forwarded-Proto", "").split(",")[0].strip()
        forwarded_host = handler.headers.get("X-Forwarded-Host", "").split(",")[0].strip()
        host = forwarded_host or handler.headers.get("Host", "").strip()
        if host:
            proto = forwarded_proto or ("https" if host.endswith(".onrender.com") else "http")
            return f"{proto}://{host}".rstrip("/")
    return ""


def get_git_revision() -> str:
    env_revision = os.getenv("RENDER_GIT_COMMIT", "").strip() or os.getenv("GIT_COMMIT", "").strip()
    if env_revision:
        return env_revision[:7]
    git_dir = Path(__file__).with_name(".git")
    if git_dir.exists():
        try:
            import subprocess

            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=Path(__file__).parent,
                capture_output=True,
                text=True,
                check=True,
            )
            revision = result.stdout.strip()
            if revision:
                return revision
        except Exception:
            pass
    return ""


def build_deployment_status(config: dict, handler: BaseHTTPRequestHandler | None = None) -> dict[str, object]:
    output_root, frames_dir, outputs_dir = extract.ensure_runtime_dirs(config)
    public_url = get_public_base_url(handler)
    credentials_path = extract.credentials_path_for(config)
    sheet_id = str(config.get("google_sheet_id", "")).strip()
    worksheet = str(config.get("worksheet", extract.DEFAULT_WORKSHEET)).strip() or extract.DEFAULT_WORKSHEET
    gemini_ready = extract.has_gemini_api_key()
    credentials_ready = credentials_path.exists()
    is_render = bool(os.getenv("RENDER", "").strip() or os.getenv("RENDER_SERVICE_ID", "").strip())
    return {
        "public_url": public_url,
        "ping_url": f"{public_url}/ping" if public_url else "",
        "git_revision": get_git_revision(),
        "runtime": "render" if is_render else "local",
        "gemini_ready": gemini_ready,
        "google_sheet_id": sheet_id,
        "worksheet": worksheet,
        "credentials_ready": credentials_ready,
        "sheets_ready": bool(sheet_id and credentials_ready),
        "app_support_dir": str(extract.APP_SUPPORT_DIR),
        "output_root": str(output_root),
        "frames_dir": str(frames_dir),
        "outputs_dir": str(outputs_dir),
        "credentials_path": str(credentials_path),
        "models": list(extract.MODEL_CANDIDATES),
    }


def normalize_result_row(row: dict[str, str]) -> dict[str, str]:
    normalized = {
        "카메라 워킹": (row.get("카메라 워킹") or "").strip(),
        "프롬프트(영문)": (row.get("프롬프트(영문)") or "").strip(),
        "내용": (row.get("내용") or row.get("한줄번역") or "").strip(),
        "링크": (row.get("링크") or "").strip(),
    }
    meta = row.get("__meta")
    if isinstance(meta, dict) and meta:
        normalized["__meta"] = meta
    return normalized


def read_local_results_table(config: dict) -> list[dict[str, str]]:
    csv_path = extract.csv_path_for(config)
    if not csv_path.exists():
        return []
    meta_by_url = extract.load_results_metadata(config)
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized = normalize_result_row(row)
        url = normalized.get("링크", "")
        if url and url in meta_by_url:
            normalized["__meta"] = meta_by_url[url]
        normalized_rows.append(normalized)
    return normalized_rows


def read_sheet_results_table(config: dict) -> list[dict[str, str]]:
    google_sheet_id = str(config.get("google_sheet_id", "")).strip()
    worksheet_name = str(config.get("worksheet", extract.DEFAULT_WORKSHEET)).strip() or extract.DEFAULT_WORKSHEET
    credentials_path = extract.credentials_path_for(config)
    if not google_sheet_id or not credentials_path.exists():
        return []
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        return []

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_file(str(credentials_path), scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(google_sheet_id)
        ws = sh.worksheet(worksheet_name)
        values = ws.get_all_values()
    except Exception:
        return []
    if not values or len(values) < 2:
        return []

    headers = values[0]
    rows: list[dict[str, str]] = []
    for raw in values[1:]:
        row = {header: (raw[idx] if idx < len(raw) else "") for idx, header in enumerate(headers)}
        normalized = normalize_result_row(row)
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def merge_result_rows(primary_rows: list[dict[str, str]], secondary_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in primary_rows + secondary_rows:
        normalized = normalize_result_row(row)
        key = normalized["링크"] or f"{normalized['내용']}|{normalized['프롬프트(영문)'][:80]}"
        if not key or key in seen:
            continue
        seen.add(key)
        merged.append(normalized)
    return merged


def build_row_meta_text(row: dict[str, str], cameras: list[str] | None = None) -> str:
    link = row.get("링크", "")
    thumb = detect_source_code(link)
    source_label = "Instagram" if thumb == "IG" else ("YouTube" if thumb == "YT" else ("AI Draft" if thumb == "AI" else "Web"))
    camera_parts = cameras if cameras is not None else parse_camera_parts(row.get("카메라 워킹", ""))
    meta_parts = [source_label, ("카메라 " + ", ".join(camera_parts)) if camera_parts else "미분류"]
    extra = row.get("__meta")
    if isinstance(extra, dict):
        source_refs = extra.get("source_refs")
        if isinstance(source_refs, list) and source_refs:
            meta_parts.append(f"참조 {len(source_refs)}개")
        if extra.get("source") == "extract" and extra.get("warning"):
            meta_parts.append("부분 보정")
    return " · ".join(part for part in meta_parts if part)


def read_results_table(config: dict) -> list[dict[str, str]]:
    local_rows = read_local_results_table(config)
    sheet_rows = read_sheet_results_table(config)
    return merge_result_rows(local_rows, sheet_rows)


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
            last_result: dict | None = None
            for attempt in range(2):
                try:
                    result = extract.run_pipeline(url)
                    last_result = result
                    ok = bool(result.get("success"))
                    usage = result.get("gemini_usage") or {}
                    cost_text = ""
                    if usage.get("krw_estimate"):
                        cost_text = f" · 약 {usage['krw_estimate']:.0f}원"
                    message = result.get("sheet_status") or result.get("error") or "추출 완료"
                    if ok and result.get("camera"):
                        message = f"추출 완료 · {result['camera']}{cost_text}"
                    elif ok:
                        message = f"추출 완료{cost_text}"
                    elif cost_text:
                        message = f"{message}{cost_text}"
                    transient_error = not ok and any(keyword in (message or "") for keyword in ["503", "UNAVAILABLE", "429"])
                    if transient_error and attempt == 0:
                        STATE.set_runtime_message(f"재시도 중 ({index}/{total})", "Gemini 과부하로 1회 자동 재시도합니다.")
                        continue
                    break
                except Exception as exc:  # noqa: BLE001
                    ok = False
                    message = f"예외 발생: {exc}"
                    if attempt == 0:
                        STATE.set_runtime_message(f"재시도 중 ({index}/{total})", "일시 오류로 1회 자동 재시도합니다.")
                        continue
                    break
            STATE.add_result(url, ok, message)
    finally:
        STATE.finish()


def compute_runtime_metrics(config: dict, snapshot: dict | None = None) -> dict:
    snapshot = snapshot or STATE.snapshot()
    results = [row for row in read_results_table(config) if row.get("링크")]
    camera_counter: Counter[str] = Counter()
    for row in results:
        for camera in parse_camera_parts(row.get("카메라 워킹", "")):
            camera_counter[camera] += 1
    run_cost = sum(parse_cost_from_message(item.message) for item in snapshot["items"])
    assistant_cost = sum(parse_cost_from_message(item.get("meta", "")) for item in snapshot.get("chat_items", []) if isinstance(item, dict))
    current_session_cost = run_cost + assistant_cost
    success_rate_base = snapshot["items"][-50:] if snapshot["items"] else []
    if success_rate_base:
        success_rate = round((sum(1 for item in success_rate_base if item.success) / len(success_rate_base)) * 100)
    else:
        success_rate = 100 if results else 0
    return {
        "snapshot": snapshot,
        "results": results,
        "recent_results": list(reversed(results[-80:])),
        "camera_counter": camera_counter,
        "current_session_cost": current_session_cost,
        "success_rate": success_rate,
    }


class PromptExtractorHandler(BaseHTTPRequestHandler):
    server_version = "PromptExtractorWeb/3.0"

    def safe_write(self, payload: bytes) -> None:
        try:
            self.wfile.write(payload)
        except BrokenPipeError:
            return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/":
            query = urllib.parse.parse_qs(parsed.query)
            requested_view = (query.get("view") or [""])[-1]
            self.render_home(requested_view)
            return
        if parsed.path == "/api/state":
            self.serve_runtime_state()
            return
        if parsed.path == "/api/library":
            self.serve_library_state()
            return
        if parsed.path == "/api/deployment":
            self.serve_deployment_state()
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
            self.safe_write(b"ok")
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
            self.redirect("/?view=settings")
            return

        if parsed.path == "/run":
            urls = normalize_urls(form.get("urls", ""))
            if not urls:
                STATE.set_notice("링크를 한 줄에 하나씩 입력해 주세요.")
                self.redirect("/?view=run")
                return
            if not STATE.start(len(urls)):
                STATE.set_notice("이미 작업이 실행 중입니다. 현재 작업이 끝난 뒤 다시 시도해 주세요.")
                self.redirect("/?view=run")
                return
            thread = threading.Thread(target=run_worker, args=(urls,), daemon=True)
            thread.start()
            self.redirect("/?view=run")
            return

        if parsed.path == "/generate":
            message = form.get("message", "").strip()
            return_view = form.get("return_view", "").strip() or "dashboard"
            rows = [row for row in read_results_table(extract.load_config()) if row.get("링크")]
            if not message:
                STATE.set_notice("시나리오나 장면 설명을 입력해 주세요.")
                self.redirect(f"/?view={return_view}")
                return
            pinned_refs_raw = form.get("pinned_refs", "").strip()
            pinned_refs: list[dict[str, str]] = []
            if pinned_refs_raw:
                try:
                    loaded = json.loads(pinned_refs_raw)
                    if isinstance(loaded, list):
                        for item in loaded:
                            if isinstance(item, dict):
                                pinned_refs.append(normalize_result_row(item))
                except Exception:
                    pinned_refs = []
            auto_refs = select_reference_rows(message, list(reversed(rows)))
            refs = merge_reference_rows(pinned_refs, auto_refs)
            raw, error, usage = call_gemini_groom_prompt(message, refs)
            if not raw:
                raw, usage = fallback_groom_response(message, refs)
                ref_note = f" · 고정 레퍼런스 {len(pinned_refs)}개" if pinned_refs else ""
                meta = f"fallback · 약 {usage.get('krw_estimate', 0):.0f}원{ref_note}"
                ai_text = raw.get("reply_ko", "초안을 생성했습니다.")
                prompt = raw.get("prompt_en", "")
            else:
                ref_note = f" · 고정 레퍼런스 {len(pinned_refs)}개" if pinned_refs else ""
                meta = f"Gemini 그루밍 완료 · 약 {usage.get('krw_estimate', 0):.0f}원{ref_note}"
                ai_text = raw.get("reply_ko", "그루밍된 프롬프트를 만들었습니다.")
                prompt = raw.get("prompt_en", "")
            summary_text = raw.get("summary_ko", "") or ai_text
            camera_tags = [str(tag).strip() for tag in raw.get("camera_tags", []) if str(tag).strip()]
            ref_indexes = [int(idx) for idx in raw.get("reference_indexes", []) if isinstance(idx, int) or str(idx).isdigit()]
            selected_refs = []
            for idx in ref_indexes:
                if 1 <= idx <= len(refs):
                    selected_refs.append(refs[idx - 1])
            if not selected_refs:
                selected_refs = refs[:3]
            simplified_refs = [
                {
                    "내용": ref.get("내용", ""),
                    "카메라 워킹": ref.get("카메라 워킹", ""),
                    "링크": ref.get("링크", ""),
                }
                for ref in selected_refs
            ]
            if error and not raw.get("reply_ko"):
                ai_text = f"{ai_text}\n\n(참고: {error})"
            STATE.add_chat_pair(message, ai_text, prompt=prompt, refs=simplified_refs, meta=meta, summary=summary_text, camera_tags=camera_tags)
            self.redirect(f"/?view={return_view}")
            return

        if parsed.path == "/save-generated":
            return_view = form.get("return_view", "").strip() or "generate"
            index_value = form.get("chat_index", "").strip()
            try:
                chat_index = int(index_value)
            except ValueError:
                STATE.set_notice("저장할 생성 결과를 찾지 못했습니다.")
                self.redirect(f"/?view={return_view}")
                return
            item = STATE.get_chat_item(chat_index)
            if not item or not item.get("prompt"):
                STATE.set_notice("저장할 프롬프트가 없습니다.")
                self.redirect(f"/?view={return_view}")
                return
            source_request = ""
            if chat_index > 0:
                prev_item = STATE.get_chat_item(chat_index - 1)
                if prev_item and prev_item.get("role") == "user":
                    source_request = str(prev_item.get("text", "")).strip()
            result = extract.save_generated_result(
                prompt=item.get("prompt", ""),
                summary=item.get("summary", "") or item.get("text", ""),
                camera_tags=item.get("camera_tags", []) or [],
                metadata={
                    "source_refs": item.get("refs", []) or [],
                    "request": source_request,
                    "generator_meta": item.get("meta", ""),
                },
            )
            STATE.set_notice(result.get("sheet_status") or "생성 결과 저장 완료")
            self.redirect(f"/?view={return_view}")
            return

        if parsed.path == "/chat/clear":
            return_view = form.get("return_view", "").strip() or "dashboard"
            STATE.clear_chat()
            self.redirect(f"/?view={return_view}")
            return

        if parsed.path == "/delete":
            url = form.get("url", "").strip()
            if not url:
                STATE.set_notice("삭제할 링크가 없습니다.")
                self.redirect("/?view=library")
                return
            result = extract.delete_result_by_url(url)
            STATE.set_notice(result.get("sheet_status") or "삭제 완료")
            self.redirect("/?view=library")
            return

        if parsed.path == "/clear":
            result = extract.clear_all_results()
            STATE.set_notice(result.get("sheet_status") or "전체 삭제 완료")
            self.redirect("/?view=library")
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def render_home(self, requested_view: str = "") -> None:
        config = extract.load_config()
        runtime = compute_runtime_metrics(config)
        snapshot = runtime["snapshot"]
        results = runtime["results"]
        recent_results = runtime["recent_results"]
        sheet_id = str(config.get("google_sheet_id", "")).strip()
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit" if sheet_id else ""
        gemini_ready = extract.has_gemini_api_key()
        credentials_ready = extract.credentials_path_for(config).exists()
        initial_view = requested_view if requested_view in VALID_VIEWS else ("run" if snapshot["running"] else ("dashboard" if results else "run"))
        camera_counter = runtime["camera_counter"]
        current_session_cost = runtime["current_session_cost"]
        success_rate = runtime["success_rate"]
        deployment_status = build_deployment_status(config, self)

        template = self._load_template()
        template = re.sub(
            r'<div class="brand">.*?</div>\s*(?=<div class="nav-group">)',
            self._render_brand_block(),
            template,
            count=1,
            flags=re.S,
        )
        template = re.sub(
            r'(<button class="nav-item" data-view="dashboard">.*?<div[^>]*>)(\s*)대시보드(\s*)(</div>)',
            r'\1\2레퍼런스 허브\3\4',
            template,
            count=1,
            flags=re.S,
        )
        template = template.replace("\n        대시보드\n", "\n        레퍼런스 허브\n")
        template = template.replace("<title>Grommy · AI Prompt Groomer</title>", "<title>Grommy G · Cloud Prompt Groomer</title>", 1)
        template = template.replace("</style>", f"{self._build_layout_overrides()}</style>", 1)
        template = template.replace("<body>", f'<body data-initial-view="{self._escape_attr(initial_view)}">', 1)
        if snapshot["running"]:
            template = template.replace("</head>", '<meta http-equiv="refresh" content="2"></head>', 1)

        notice_html = (
            f'<div class="card" style="margin-bottom:16px; border-color:#c8dfd2; background:#f1f7f3;">'
            f'<div class="card-title" style="font-size:14px; color:var(--accent);">안내</div>'
            f'<div class="card-sub" style="margin-top:6px; color:var(--ink-2);">{self._escape(snapshot["notice"])}</div>'
            f'</div>'
        ) if snapshot["notice"] else ""
        if notice_html:
            template = template.replace('<main class="main">', f'<main class="main">\n{notice_html}', 1)

        template = self._replace_view_section(template, "dashboard", self._render_dashboard_view(snapshot, recent_results, camera_counter, current_session_cost, success_rate, gemini_ready, sheet_url))
        template = self._replace_view_section(template, "run", self._render_run_view(snapshot))
        template = self._replace_view_section(template, "generate", self._render_generate_view(recent_results, camera_counter))
        template = self._replace_view_section(template, "library", self._render_library_view(recent_results, camera_counter, sheet_url))
        template = self._replace_view_section(
            template,
            "settings",
            self._render_settings_view(config, gemini_ready, credentials_ready, sheet_url, deployment_status),
        )

        template = template.replace('<span class="count">128</span>', f'<span class="count">{len(results)}</span>', 1)
        template = template.replace('Gemini 2.5 Flash · 그루밍 규칙 24개 로드됨', f'Gemini 직접 분석 · 카메라 규칙 {len(camera_counter) or 0}개 로드됨', 1)
        template = template.replace('<main class="main">', '<main class="main"><div class="workspace-shell"><div class="workspace-left">', 1)
        template = template.replace('</main>', f'</div>{self._render_global_assistant_panel(snapshot, recent_results, initial_view)}</div></main>', 1)

        script = self._build_client_script()
        template = re.sub(r"<script>.*?</script>\s*</body>", lambda _m: f"<script>{script}</script>\n</body>", template, flags=re.S)

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.safe_write(template.encode("utf-8"))

    def serve_runtime_state(self) -> None:
        config = extract.load_config()
        runtime = compute_runtime_metrics(config)
        snapshot = runtime["snapshot"]
        payload = {
            "running": snapshot["running"],
            "status": snapshot["status"],
            "summary": snapshot["summary"],
            "total": snapshot["total"],
            "completed": snapshot["completed"],
            "success_count": snapshot["success_count"],
            "items": [
                {"url": item.url, "success": item.success, "message": item.message}
                for item in snapshot["items"][-8:]
            ],
            "results_count": len(runtime["results"]),
            "current_session_cost": runtime["current_session_cost"],
            "success_rate": runtime["success_rate"],
            "top_cameras": runtime["camera_counter"].most_common(6),
            "notice": snapshot["notice"],
        }
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.safe_write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def serve_library_state(self) -> None:
        config = extract.load_config()
        runtime = compute_runtime_metrics(config)
        rows = runtime["recent_results"]
        payload = {
            "rows": rows,
            "camera_counts": runtime["camera_counter"].most_common(20),
            "count": len(rows),
        }
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.safe_write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def serve_deployment_state(self) -> None:
        config = extract.load_config()
        payload = build_deployment_status(config, self)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.safe_write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def _load_template(self) -> str:
        return TEMPLATE_PATH.read_text(encoding="utf-8")

    def _render_brand_block(self) -> str:
        return '''
<div class="brand">
  <div class="brand-mark grommy-logo" aria-label="Grommy G 로고">
    <svg width="36" height="36" viewBox="0 0 92 92" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="gCloudStroke" x1="11" y1="16" x2="80" y2="73" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#8cf9ff"/>
          <stop offset="60%" stop-color="#45dbe8"/>
          <stop offset="100%" stop-color="#37b8d1"/>
        </linearGradient>
        <linearGradient id="gCloudFill" x1="18" y1="18" x2="76" y2="76" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#25325a"/>
          <stop offset="55%" stop-color="#1a2342"/>
          <stop offset="100%" stop-color="#141c35"/>
        </linearGradient>
        <linearGradient id="gLetterFill" x1="18" y1="10" x2="56" y2="62" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#ffffff"/>
          <stop offset="100%" stop-color="#e7f5ff"/>
        </linearGradient>
        <linearGradient id="gGlow" x1="20" y1="20" x2="86" y2="78" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stop-color="#52f0eb"/>
          <stop offset="100%" stop-color="#4d88ff"/>
        </linearGradient>
      </defs>
      <path d="M67.6 31.5c6.6 0 12 4.8 12.9 11.1 4.4.8 7.7 4.5 7.7 8.9 0 5.3-4.3 9.7-9.8 9.7H34.5c-14.5 0-26.3-11.2-26.3-25.1 0-11 7.4-20.4 17.8-23.5C29.2 7.3 37.3 3 46.6 3 57.7 3 67 9.8 70 19.5c.8-.1 1.6-.2 2.4-.2Z" fill="url(#gCloudFill)"/>
      <path d="M65.8 30.4c6.1 0 11.2 4.4 12.3 10.3 4.5.8 7.9 4.6 7.9 9.2 0 5.5-4.6 10-10.2 10H34.3c-14 0-25.3-10.7-25.3-24 0-10.9 7.6-20.1 18-22.8C30.2 8 37.2 4 45.4 4c9.9 0 18.1 6.1 21 14.7.9-.2 1.8-.3 2.7-.3Z" fill="none" stroke="url(#gCloudStroke)" stroke-width="4.4" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M35.4 17c-13 0-23.7 10.3-23.7 23 0 12.6 10.7 22.9 23.7 22.9 9.8 0 16.4-4.6 20.4-11.6V38.6H38.6v8.1h7.9c-1.7 4.6-5.7 7.4-11.2 7.4-7.2 0-13.1-5.7-13.1-12.8 0-7 5.9-12.8 13.1-12.8 3.4 0 6.6 1.3 9.1 3.6l6.2-6.1C46.6 19.2 41.2 17 35.4 17Z" fill="url(#gLetterFill)"/>
      <path d="M57.6 56c0-8.7 7-15.7 15.7-15.7 4.5 0 8.6 1.9 11.4 5-1.6-7.3-8.3-12.8-16.1-12.8-9.1 0-16.5 7.3-16.5 16.4 0 8 5.8 14.8 13.6 16.1-5.2-1.6-8.1-4.8-8.1-9Z" fill="url(#gGlow)" opacity="0.22"/>
    </svg>
  </div>
  <div>
    <div class="brand-name">Grommy G</div>
  </div>
</div>'''.strip()

    def _build_layout_overrides(self) -> str:
        return """

  .main { max-width: none; width: calc(100vw - 248px); padding: 14px 22px 20px; }
  .workspace-shell {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(360px, 1fr);
    gap: 18px;
    min-height: calc(100vh - 28px);
    align-items: start;
  }
  .workspace-left {
    min-width: 0;
    max-height: calc(100vh - 28px);
    overflow-y: scroll;
    padding-right: 8px;
    scrollbar-gutter: stable;
  }
  .workspace-left::-webkit-scrollbar,
  .assistant-scroll::-webkit-scrollbar,
  .chat-body::-webkit-scrollbar {
    width: 12px;
  }
  .workspace-left::-webkit-scrollbar-thumb,
  .assistant-scroll::-webkit-scrollbar-thumb,
  .chat-body::-webkit-scrollbar-thumb {
    background: rgba(73, 97, 120, 0.28);
    border-radius: 999px;
    border: 2px solid transparent;
    background-clip: padding-box;
  }
  .workspace-sidepanel {
    position: sticky;
    top: 0;
    height: calc(100vh - 28px);
    display: flex;
    flex-direction: column;
    min-width: 0;
    align-self: start;
  }
  .assistant-panel {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sm);
    min-height: calc(100vh - 28px);
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  .assistant-scroll {
    flex: 1;
    overflow-y: auto;
  }
  .assistant-panel .chat-header {
    position: sticky;
    top: 0;
    z-index: 2;
    background: var(--surface);
    border-bottom: 1px solid var(--line-2);
  }
  .assistant-panel .assistant-composer {
    position: sticky;
    bottom: 0;
    background: var(--surface);
    border-top: 1px solid var(--line-2);
    z-index: 2;
  }
  .assistant-composer textarea {
    min-height: 92px;
    resize: vertical;
  }
  .hub-topbar {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    align-items: end;
    gap: 12px;
    margin-bottom: 10px;
  }
  .hub-metrics {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    justify-content: flex-start;
  }
  .hub-pill {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 7px 10px;
    min-width: 96px;
    box-shadow: var(--shadow-sm);
  }
  .hub-pill-label {
    font-size: 10px;
    color: var(--muted);
    margin-bottom: 2px;
    letter-spacing: 0.02em;
  }
  .hub-pill-value {
    font-size: 15px;
    font-weight: 700;
    letter-spacing: -0.02em;
  }
  .hub-strip {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(220px, 280px);
    gap: 12px;
    margin-bottom: 16px;
  }
  .mini-card {
    background: var(--surface);
    border: 1px solid var(--line);
    border-radius: var(--radius-md);
    padding: 14px 16px;
    box-shadow: var(--shadow-sm);
  }
  .brand-mark.grommy-logo {
    width: 48px;
    height: 48px;
    border-radius: 16px;
    background: radial-gradient(circle at 30% 24%, rgba(255,255,255,0.14), rgba(255,255,255,0) 42%), linear-gradient(145deg, #1b2445 0%, #1a223d 48%, #15203a 100%);
    box-shadow: inset 0 0 0 1px rgba(90, 240, 239, 0.18), 0 12px 26px rgba(11, 18, 37, 0.34);
  }
  .brand-sub { display:none; }
  .brand-name { letter-spacing: -0.02em; }
  .hub-topbar .page-title { margin-bottom: 4px; }
  .hub-strip .mini-card:last-child { justify-self: end; width: min(280px, 100%); }
  .hub-inline-meta {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .hub-inline-meta .card-sub { margin: 0; }
  .assistant-panel .chat-header { padding: 18px 18px 14px; }
  .assistant-panel .chat-body { padding: 18px 18px 12px; }
  .assistant-panel .chat-context { background: transparent; }
  .assistant-panel .context-scroll { padding: 0 18px 18px; }
  .assistant-panel .chat-composer { padding: 16px 18px 18px; }
  .topbar-actions .topbar-status { white-space: nowrap; }
  .assistant-header-actions { margin-left: auto; display: flex; gap: 8px; }
  .assistant-empty {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 140px;
    color: var(--muted);
    text-align: center;
    padding: 24px;
  }
  .assistant-refs {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 10px;
  }
  .assistant-refs .ai-ref-pill {
    cursor: default;
  }
  .context-card-meta {
    font-size: 10.5px;
    color: var(--muted);
    margin-bottom: 6px;
  }
  .context-card-actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
  }
  .context-card-actions .btn,
  .context-card-actions .copy-btn {
    font-size: 10.5px;
    padding: 6px 8px;
    min-height: 30px;
  }
  @media (max-width: 1180px) {
    .main { width: calc(100vw - 248px); }
    .workspace-shell { grid-template-columns: 1fr; }
    .workspace-left {
      max-height: none;
      overflow: visible;
      padding-right: 0;
    }
    .workspace-sidepanel { display: none; }
    .hub-strip { grid-template-columns: 1fr; }
  }
"""

    def _replace_view_section(self, template: str, name: str, replacement: str) -> str:
        pattern = rf'<section class="view(?: active)?" data-view="{re.escape(name)}">.*?</section>'
        return re.sub(pattern, replacement, template, count=1, flags=re.S)

    def _render_dashboard_view(self, snapshot: dict, recent_results: list[dict[str, str]], camera_counter: Counter[str], current_session_cost: float, success_rate: int, gemini_ready: bool, sheet_url: str) -> str:
        latest_items = snapshot["items"][-5:]
        if latest_items:
            activity_items = "".join(self._render_activity_item(item.url, item.message, item.success, "방금") for item in reversed(latest_items))
        else:
            activity_items = "".join(
                self._render_activity_item(row.get("링크", ""), row.get("내용") or row.get("프롬프트(영문)", "저장됨")[:60], True, "저장됨")
                for row in recent_results[:5]
            ) or '<li class="activity-item"><div><div class="activity-msg">아직 저장된 작업이 없습니다.</div></div></li>'

        top_cameras = camera_counter.most_common(5)
        max_count = top_cameras[0][1] if top_cameras else 1
        top_camera_html = "".join(
            f'''<div class="top-camera-row" style="display:flex; align-items:center; gap:10px;">
              <div class="top-camera-name" style="flex:1; font-size:13px; font-weight:600;">{self._escape(camera)}</div>
              <div style="flex:2; height:6px; background:var(--surface-3); border-radius:999px; overflow:hidden;">
                <div class="top-camera-bar" style="width:{max(12, round((count/max_count)*100))}%; height:100%; background:var(--accent); border-radius:999px;"></div>
              </div>
              <div class="top-camera-count" style="font-size:12px; color:var(--muted); font-variant-numeric:tabular-nums; min-width:26px; text-align:right;">{count}</div>
            </div>'''
            for camera, count in top_cameras
        ) or '<div class="card-sub">아직 분류된 카메라 워킹이 없습니다.</div>'

        recent_rows = "".join(
            f'''<tr>
              <td>{self._escape((row.get("내용") or "미분류 결과")[:44])}</td>
              <td>{self._escape(" / ".join(parse_camera_parts(row.get("카메라 워킹", ""))) or "미분류")}</td>
              <td>{'<span class="meta-link" style="opacity:.7;">생성 초안</span>' if detect_source_code(row.get("링크", "")) == "AI" else f'<a class="meta-link" href="{self._escape_attr(row.get("링크", ""))}" target="_blank">원본 열기 →</a>'}</td>
            </tr>'''
            for row in recent_results[:5]
        ) or '<tr><td colspan="3" class="empty">아직 저장된 결과가 없습니다.</td></tr>'

        sheet_button = f'''<button class="btn" onclick="window.open('{self._escape_attr(sheet_url)}', '_blank')">Google Sheet 열기</button>''' if sheet_url else ''

        return f'''
<section class="view" data-view="dashboard">
  <div class="topbar hub-topbar">
    <div>
      <div class="page-title">레퍼런스 허브</div>
      <div class="page-sub">쌓인 결과를 탐색하고, 바로 추출하거나 우측 어시스턴트로 새 프롬프트를 그루밍할 수 있습니다.</div>
    </div>
    <div class="hub-metrics">
      <div class="hub-pill">
        <div class="hub-pill-label">저장 결과</div>
        <div class="hub-pill-value" id="metric-results-count">{len(recent_results)}</div>
      </div>
      <div class="hub-pill">
        <div class="hub-pill-label">추정 비용</div>
        <div class="hub-pill-value" id="metric-session-cost">₩{current_session_cost:.0f}</div>
      </div>
    </div>
  </div>

  <div class="hub-strip">
    <div class="mini-card">
      <div class="card-title">카메라 태깅 현황</div>
      <div class="card-sub">현재 아카이브에 저장된 카메라 분류 {len(camera_counter)}개</div>
      <div style="margin-top:12px; display:flex; flex-wrap:wrap; gap:8px;">
        {''.join(f'<span class="tag">{self._escape(camera)}</span>' for camera, _ in camera_counter.most_common(6)) or '<span class="tag tag-muted">아직 태그 없음</span>'}
      </div>
    </div>
    <div class="mini-card">
      <div class="card-title">레퍼런스 허브</div>
      <div class="hub-inline-meta" style="margin-top:8px;">
        <div class="card-sub">최근 성공률 <strong id="metric-success-rate" style="color:var(--ink);">{success_rate}%</strong></div>
        <div class="card-sub">작업공간 고정 패널 모드</div>
      </div>
      <div style="margin-top:12px; display:flex; gap:8px; flex-wrap:wrap;">
        {sheet_button}
        <button class="btn btn-primary" onclick="switchView('run')">새 추출 시작</button>
      </div>
    </div>
  </div>

  <div class="run-grid">
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">최근 추출 흐름</div>
          <div class="card-sub">현재 세션과 최근 저장 결과를 함께 보여줍니다.</div>
        </div>
        <div class="card-header-action"><button class="btn btn-sm" onclick="switchView('library')">라이브러리 보기 →</button></div>
      </div>
      <ul class="activity-list" style="max-height:none;">{activity_items}</ul>
    </div>

    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">카메라 워킹 Top 5</div>
          <div class="card-sub">라이브러리에서 가장 자주 등장한 분류</div>
        </div>
      </div>
      <div style="display:flex; flex-direction:column; gap:10px;">{top_camera_html}</div>
    </div>
  </div>

  <div class="card">
    <div class="card-header">
      <div>
        <div class="card-title">최근 저장된 결과</div>
        <div class="card-sub">내용과 카메라 워킹을 빠르게 확인한 뒤 라이브러리로 넘어갈 수 있습니다.</div>
      </div>
      <div class="card-header-action"><button class="btn btn-sm" onclick="switchView('library')">전체 보기 →</button></div>
    </div>
    <div class="results-table-wrap">
      <table class="results">
        <thead><tr><th>내용</th><th>카메라 워킹</th><th>링크</th></tr></thead>
        <tbody>{recent_rows}</tbody>
      </table>
    </div>
  </div>
</section>'''

    def _render_generate_view(self, recent_results: list[dict[str, str]], camera_counter: Counter[str]) -> str:
        recent_tags = "".join(
            f'<button type="button" class="tag" onclick="filterByCameraTag(\'{self._escape_attr(camera)}\')">{self._escape(camera)}</button>'
            for camera, _ in camera_counter.most_common(10)
        ) or '<span class="tag tag-muted">카메라 태그 없음</span>'
        cards: list[str] = []
        for row in recent_results[:3]:
            prompt_text = row.get("프롬프트(영문)", "")
            prompt_preview = prompt_text[:220] + ("…" if len(prompt_text) > 220 else "")
            cards.append(
                f'''<div class="mini-card">
                    <div class="card-title">{self._escape(row.get("내용", "미분류"))}</div>
                    <div class="card-sub" style="margin-top:6px;">{" / ".join(parse_camera_parts(row.get("카메라 워킹",""))) or "미분류"}</div>
                    <div style="margin-top:10px; font-size:12px; color:var(--muted); line-height:1.6;">{self._escape(prompt_preview)}</div>
                </div>'''
            )
        reference_cards = "".join(cards) or '<div class="mini-card"><div class="card-sub">아직 참고할 레퍼런스가 없습니다.</div></div>'

        return f'''
<section class="view" data-view="generate">
  <div class="topbar">
    <div>
      <div class="page-title">그루밍 작업공간</div>
      <div class="page-sub">우측 AI 시나리오 어시스턴트에 장면 설명을 입력하면, 이 아카이브의 레퍼런스를 참고해 프롬프트를 생성합니다.</div>
    </div>
  </div>
  <div class="card" style="margin-bottom:16px;">
    <div class="card-header">
      <div>
        <div class="card-title">빠른 카메라 태그 선택</div>
        <div class="card-sub">태그를 누르면 라이브러리 필터에도 바로 반영됩니다.</div>
      </div>
    </div>
    <div class="tag-row">{recent_tags}</div>
  </div>
  <div style="display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px;">
    {reference_cards}
  </div>
</section>'''

    def _render_global_assistant_panel(self, snapshot: dict, recent_results: list[dict[str, str]], initial_view: str) -> str:
        chat_items = snapshot.get("chat_items", []) or [DEFAULT_CHAT_GREETING.copy()]
        selected_refs = recent_results[:4]
        ref_blocks: list[str] = []
        for idx, row in enumerate(selected_refs, start=1):
            prompt_text = row.get("프롬프트(영문)", "")
            prompt_preview = prompt_text[:180] + ("…" if len(prompt_text) > 180 else "")
            payload = {
                "내용": row.get("내용", ""),
                "카메라 워킹": row.get("카메라 워킹", ""),
                "프롬프트(영문)": row.get("프롬프트(영문)", ""),
                "링크": row.get("링크", ""),
            }
            payload_attr = self._escape_attr(json.dumps(payload, ensure_ascii=False))
            meta_text = build_row_meta_text(row, parse_camera_parts(row.get("카메라 워킹", "")))
            link = row.get("링크", "")
            thumb = detect_source_code(link)
            action = (
                '<span class="meta-link" style="opacity:.7;">생성 초안</span>'
                if thumb == "AI" or not link
                else f'<button type="button" class="copy-btn" onclick="event.stopPropagation(); window.open(\'{self._escape_attr(link)}\', \'_blank\'); return false;">원본 열기</button>'
            )
            ref_blocks.append(
                f'''<div class="context-card">
                  <div class="context-card-head">
                    <span class="context-card-num">{idx}</span>
                    <span class="context-card-rule">{self._escape(row.get("내용","미분류 레퍼런스"))}</span>
                  </div>
                  <div class="context-card-tags">{''.join(f'<span class="tag">{self._escape(tag)}</span>' for tag in parse_camera_parts(row.get("카메라 워킹",""))[:3]) or '<span class="tag tag-muted">미분류</span>'}</div>
                  <div class="context-card-meta">{self._escape(meta_text)}</div>
                  <div class="context-card-body">{self._escape(prompt_preview)}</div>
                  <div class="context-card-actions">
                    <button type="button" class="copy-btn" data-pin-payload="{payload_attr}" onclick="event.stopPropagation(); setPinnedReferences([JSON.parse(this.dataset.pinPayload)]); switchView('generate'); return false;">참조 고정</button>
                    {action}
                  </div>
                </div>'''
            )
        ref_cards = "".join(ref_blocks) or '<div class="assistant-empty">아직 아카이브에 저장된 레퍼런스가 없습니다.</div>'

        messages_html = []
        for message_index, item in enumerate(chat_items):
            role = item.get("role", "ai")
            bubble_class = "user" if role == "user" else "ai"
            avatar = "U" if role == "user" else "G"
            text = self._escape(item.get("text", ""))
            prompt = item.get("prompt", "")
            refs = item.get("refs", []) or []
            meta = item.get("meta", "")
            refs_html = ""
            if refs:
                refs_html = '<div class="assistant-refs">' + "".join(
                    f'<span class="ai-ref-pill"><span class="ref-num">{idx}</span>{self._escape(ref.get("내용","레퍼런스"))}</span>'
                    for idx, ref in enumerate(refs, start=1)
                ) + '</div>'
            prompt_html = ""
            if prompt:
                prompt_html = f'''
<div class="ai-response-prompt">
  <div class="prompt-tools">
    <button class="copy-btn">복사</button>
    <form method="post" action="/save-generated" style="display:inline;">
      <input type="hidden" name="return_view" value="{self._escape_attr(initial_view)}">
      <input type="hidden" name="chat_index" value="{message_index}">
      <button class="copy-btn" type="submit">아카이브 저장</button>
    </form>
  </div>
  {self._escape(prompt)}
</div>'''
            meta_html = f'<div class="chat-meta" style="margin-top:8px;">{self._escape(meta)}</div>' if meta and role == "ai" else ""
            messages_html.append(
                f'''<div class="chat-msg {bubble_class}">
                      <div class="msg-avatar">{avatar}</div>
                      <div class="chat-bubble">{text}{meta_html}{prompt_html}{refs_html}</div>
                    </div>'''
            )

        return f'''
<aside class="workspace-sidepanel">
  <div class="assistant-panel">
    <div class="chat-header">
      <div class="chat-avatar">G</div>
      <div>
        <div class="chat-title">AI 시나리오 어시스턴트</div>
        <div class="chat-meta">우측 1/3 고정 패널 · 아카이브 레퍼런스 기반 그루밍</div>
      </div>
      <div class="assistant-header-actions">
        <form method="post" action="/chat/clear">
          <input type="hidden" name="return_view" value="{self._escape_attr(initial_view)}">
          <button class="icon-btn" type="submit" title="대화 초기화">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
          </button>
        </form>
      </div>
    </div>
    <div class="assistant-scroll">
      <div class="chat-body">{''.join(messages_html)}</div>
      <aside class="chat-context" style="border-top:1px solid var(--line-2); border-left:0; border-right:0; border-bottom:0; border-radius:0;">
        <div class="context-head">
          <div class="context-title">참조 레퍼런스</div>
          <div class="context-sub">최근 저장 결과 중 자주 참고되는 항목</div>
        </div>
        <div class="context-scroll">{ref_cards}</div>
      </aside>
    </div>
    <form class="chat-composer assistant-composer" method="post" action="/generate">
      <input type="hidden" name="return_view" value="{self._escape_attr(initial_view)}">
      <input type="hidden" name="pinned_refs" id="pinned-refs-input" value="">
      <div class="composer-box">
        <textarea class="composer-input" name="message" placeholder="만들고 싶은 장면, 분위기, 카메라 무빙을 적어주세요. 예: 비 오는 밤, 시간이 멈춘 골목, 드론 샷으로 내려오며 주인공을 감싸는 장면"></textarea>
        <div id="pinned-ref-summary" style="display:flex; gap:8px; flex-wrap:wrap; margin:0 0 10px; font-size:12px; color:var(--muted);">
          <span>고정된 레퍼런스 없음</span>
        </div>
        <div class="composer-actions">
          <span style="font-size:11.5px; color:var(--muted);">클라우드 레퍼런스와 Gemini를 함께 사용합니다</span>
          <button class="btn btn-primary send" type="submit">그루밍</button>
        </div>
      </div>
    </form>
  </div>
</aside>'''

    def _render_run_view(self, snapshot: dict) -> str:
        width = 0 if not snapshot["total"] else round((snapshot["completed"] / snapshot["total"]) * 100)
        badge = "실행 중" if snapshot["running"] else "대기 중"
        items_html = "".join(self._render_activity_item(item.url, item.message, item.success, f"{index+1}건") for index, item in enumerate(snapshot["items"][-8:]))
        if not items_html:
            items_html = '<li class="activity-item"><div><div class="activity-msg">아직 실행된 작업이 없습니다. 링크를 넣고 시작하면 이곳에 진행 내역이 쌓입니다.</div></div></li>'

        return f'''
<section class="view" data-view="run">
  <div class="topbar">
    <div>
      <div class="page-title">추출 실행</div>
      <div class="page-sub">링크를 넣으면 영상을 임시 다운로드하고, Gemini가 직접 영상을 읽어 프롬프트를 복원합니다.</div>
    </div>
    <div class="topbar-actions">
      <span class="topbar-status"><span class="status-dot"></span>{self._escape(snapshot['status'])}</span>
    </div>
  </div>

  <div class="run-grid">
    <div>
      <form class="input-wrap" method="post" action="/run">
        <div class="input-tabs">
          <button class="input-tab active" type="button">링크 붙여넣기</button>
          <button class="input-tab" type="button" disabled>파일로 가져오기</button>
          <button class="input-tab" type="button" disabled>클립보드에서 가져오기</button>
        </div>
        <textarea class="input-area" id="run-urls" name="urls" placeholder="https://www.instagram.com/reel/DXGdtNtEwhu/\nhttps://www.instagram.com/reel/DVkP9tR_xYq/\nhttps://youtu.be/..."></textarea>
        <div class="input-footer">
          <div class="input-hint">
            <strong class="link-count">0</strong>개 링크 감지됨 · 예상 비용 <strong class="cost-estimate">약 0원</strong>
          </div>
          <div class="input-actions">
            <button class="btn btn-sm" type="button" id="clear-urls">비우기</button>
            <button class="btn btn-primary btn-lg" type="submit" {'disabled' if snapshot['running'] else ''}>프롬프트 추출 시작</button>
          </div>
        </div>
      </form>

      <div class="card" style="margin-top:16px;">
        <div class="card-header">
          <div>
            <div class="card-title">추출 옵션</div>
            <div class="card-sub">현재 백엔드는 direct-video 우선, OCR fallback 구조입니다.</div>
          </div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(2,1fr); gap:16px;">
          <div class="field" style="margin:0;">
            <label class="field-label">추출 모드</label>
            <select class="field-input" disabled>
              <option>영상 직접 분석 (기본)</option>
              <option>OCR fallback (예외 시 자동)</option>
            </select>
          </div>
          <div class="field" style="margin:0;">
            <label class="field-label">Google Sheet 반영</label>
            <select class="field-input" disabled>
              <option>기존 행 업데이트 + 신규 추가</option>
            </select>
          </div>
        </div>
      </div>
    </div>

    <div class="progress-card">
      <div class="progress-head">
        <div class="progress-title">진행 상태</div>
        <span class="progress-badge" id="run-badge">{badge}</span>
      </div>
      <div class="progress-bar"><div class="progress-fill" id="run-progress-fill" style="width:{width}%;"></div></div>
      <div class="progress-meta">
        <span id="run-progress-text"><strong style="color:var(--ink); font-weight:700;">{snapshot['completed']}</strong> / {snapshot['total']} 완료</span>
        <span id="run-progress-summary">{self._escape(snapshot['summary'])}</span>
      </div>
      <div class="progress-summary" id="run-status-line">{self._escape(snapshot['status'])} · {self._escape(snapshot['summary'])}</div>
      <ul class="activity-list" id="run-activity-list">{items_html}</ul>
    </div>
  </div>
</section>'''

    def _render_library_view(self, recent_results: list[dict[str, str]], camera_counter: Counter[str], sheet_url: str) -> str:
        filter_chips = "".join(
            f'<button class="chip" type="button" data-camera="{self._escape_attr(camera)}">{self._escape(camera)} <span class="count">{count}</span></button>'
            for camera, count in camera_counter.most_common(12)
        ) or '<span class="muted">아직 카메라 워킹 데이터가 없습니다.</span>'

        rows_html = "".join(self._render_library_row(row) for row in recent_results)
        if not rows_html:
            rows_html = '<tr><td colspan="6" class="empty">아직 저장된 결과가 없습니다.</td></tr>'

        extra_action = f'<button class="btn btn-sm" type="button" onclick="window.open(\'{self._escape_attr(sheet_url)}\', \'_blank\')">시트 열기</button>' if sheet_url else ''

        return f'''
<section class="view" data-view="library">
  <div class="topbar">
    <div>
      <div class="page-title">통합 레퍼런스 라이브러리</div>
      <div class="page-sub">카메라 태그를 고르고, 내용/프롬프트를 검색해 원하는 레퍼런스를 바로 다시 찾습니다.</div>
    </div>
    <div class="topbar-actions">
      <button class="btn" type="button" onclick="window.location='/download/csv'">CSV 내보내기</button>
      <button class="btn" type="button" onclick="window.location='/download/xlsx'">XLSX 내보내기</button>
      {extra_action}
      <button class="btn btn-primary" type="button" onclick="switchView('run')">새 추출</button>
    </div>
  </div>

  <div class="results-toolbar">
    <div class="search-box">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
      <input class="search-input" id="content-search" type="search" placeholder="예: 시간 정지, 술집, dolly, 괴물 전투">
    </div>
    <button class="btn btn-sm" type="button" disabled>고급 필터</button>
    <button class="btn btn-sm btn-ghost" type="button" id="reset-filters">필터 초기화</button>
    <form method="post" action="/clear" onsubmit="return confirm('최근 결과 전체를 삭제하시겠습니까? 시트에서도 함께 삭제됩니다.')">
      <button class="btn btn-sm btn-ghost" type="submit">전체 삭제</button>
    </form>
  </div>

  <div class="filter-bar">
    <span class="filter-label">카메라 워킹</span>
    <div id="library-filter-chips" style="display:flex; gap:8px; flex-wrap:wrap;">{filter_chips}</div>
  </div>

  <div class="results-table-wrap">
    <table class="results">
      <thead>
        <tr>
          <th class="col-thumb"></th>
          <th class="col-camera">카메라 워킹</th>
          <th class="col-prompt">프롬프트 (영문)</th>
          <th class="col-content">내용</th>
          <th class="col-meta">메타</th>
          <th class="col-actions"></th>
        </tr>
      </thead>
      <tbody id="library-results-body">{rows_html}</tbody>
    </table>
  </div>
</section>'''

    def _render_settings_view(self, config: dict, gemini_ready: bool, credentials_ready: bool, sheet_url: str, deployment_status: dict[str, object]) -> str:
        sheet_id = str(config.get("google_sheet_id", "")).strip()
        worksheet = str(config.get("worksheet", extract.DEFAULT_WORKSHEET)).strip() or extract.DEFAULT_WORKSHEET
        credentials_path = str(extract.credentials_path_for(config))
        sheet_state = "연결됨" if (sheet_id and credentials_ready) else "미설정"
        key_state = "설정됨" if gemini_ready else "미설정"
        sheet_status_class = "ok" if (sheet_id and credentials_ready) else "warn"
        key_status_class = "ok" if gemini_ready else "warn"
        sheet_button = f'<button class="btn" type="button" onclick="window.open(\'{self._escape_attr(sheet_url)}\', \'_blank\')">Google Sheet 열기</button>' if sheet_url else ''
        public_url = str(deployment_status.get("public_url", "") or "")
        ping_url = str(deployment_status.get("ping_url", "") or "")
        runtime_name = "Render" if deployment_status.get("runtime") == "render" else "로컬/기타"
        git_revision = str(deployment_status.get("git_revision", "") or "")
        outputs_dir = str(deployment_status.get("outputs_dir", "") or "")
        models = " / ".join(deployment_status.get("models", []) or [])
        deploy_status_html = f'''
      <div class="card" style="margin-bottom:16px;">
        <div class="card-header">
          <div>
            <div class="card-title">배포 준비 상태</div>
            <div class="card-sub">고정 URL 배포 전에 필요한 값이 모두 준비됐는지 확인합니다.</div>
          </div>
          <div class="card-header-action"><span class="status-pill {'ok' if public_url else 'warn'}">{'고정 URL 감지' if public_url else '고정 URL 미설정'}</span></div>
        </div>
        <div style="display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px;">
          <div class="mini-card">
            <div class="card-title">런타임</div>
            <div class="card-sub" style="margin-top:6px;">{self._escape(runtime_name)}{f' · {self._escape(git_revision)}' if git_revision else ''}</div>
          </div>
          <div class="mini-card">
            <div class="card-title">모델</div>
            <div class="card-sub" style="margin-top:6px;">{self._escape(models or 'gemini-2.5-flash')}</div>
          </div>
          <div class="mini-card">
            <div class="card-title">공개 주소</div>
            <div class="card-sub" style="margin-top:6px; word-break:break-all;">{self._escape(public_url or '아직 환경변수/프록시에서 감지되지 않았습니다.')}</div>
          </div>
          <div class="mini-card">
            <div class="card-title">헬스체크</div>
            <div class="card-sub" style="margin-top:6px; word-break:break-all;">{self._escape(ping_url or '/ping')}</div>
          </div>
          <div class="mini-card">
            <div class="card-title">출력 폴더</div>
            <div class="card-sub" style="margin-top:6px; word-break:break-all;">{self._escape(outputs_dir)}</div>
          </div>
          <div class="mini-card">
            <div class="card-title">배포 API</div>
            <div class="card-sub" style="margin-top:6px;">/api/deployment 에서 현재 상태를 JSON으로 확인할 수 있습니다.</div>
          </div>
        </div>
      </div>'''

        return f'''
<section class="view" data-view="settings">
  <div class="topbar">
    <div>
      <div class="page-title">설정</div>
      <div class="page-sub">Google Sheets 연동과 Gemini API만 관리합니다. 설정은 운영체제별 사용자 데이터 폴더에 저장됩니다.</div>
    </div>
  </div>

  <div class="settings-section">
    <nav class="settings-nav">
      <button class="settings-nav-item active">클라우드 연동 (Sheets)</button>
      <button class="settings-nav-item">그루밍 엔진 (Gemini)</button>
      <button class="settings-nav-item">앱 정보</button>
    </nav>

    <div>
      {deploy_status_html}
      <form class="card" method="post" action="/settings">
        <div class="card-header">
          <div>
            <div class="card-title">클라우드 연동 · Google Sheets</div>
            <div class="card-sub">추출된 결과가 자동으로 지정 워크시트에 누적됩니다.</div>
          </div>
          <div class="card-header-action"><span class="status-pill {sheet_status_class}">{sheet_state}</span></div>
        </div>

        <div class="field">
          <label class="field-label">Google Sheet ID</label>
          <input class="field-input" name="google_sheet_id" value="{self._escape_attr(sheet_id)}" placeholder="1DtWPwJCLsz3BkKaspfCqNpT5844hd7r736vfwPGY1bA">
          <div class="field-hint">시트 URL의 <code>/d/…/edit</code> 사이 값입니다.</div>
        </div>

        <div class="field">
          <label class="field-label">워크시트 이름</label>
          <input class="field-input" name="worksheet" value="{self._escape_attr(worksheet)}">
        </div>

        <div class="field">
          <label class="field-label">credentials.json</label>
          <div class="field-row">
            <input class="field-input" value="{self._escape_attr(credentials_path)}" readonly style="flex:1;">
          </div>
          <div class="field-hint">서비스 계정 JSON 위치입니다. 운영체제에 따라 앱 데이터 폴더 경로가 달라질 수 있습니다.</div>
        </div>

        <div class="field" style="margin-bottom:0;">
          <div class="field-row" style="justify-content:flex-end;">
            {sheet_button}
            <button class="btn btn-primary" type="submit">변경 사항 저장</button>
          </div>
        </div>
      </form>

      <form class="card" method="post" action="/settings" style="margin-top:16px;">
        <div class="card-header">
          <div>
            <div class="card-title">그루밍 엔진 · Gemini API</div>
            <div class="card-sub">영상 직접 분석을 수행하는 핵심 API 키입니다.</div>
          </div>
          <div class="card-header-action"><span class="status-pill {key_status_class}">{key_state}</span></div>
        </div>

        <div class="field">
          <label class="field-label">Gemini API Key</label>
          <input class="field-input" name="gemini_api_key" type="password" placeholder="새 키로 바꿀 때만 입력하세요">
          <div class="field-hint">키는 환경변수, 시스템 보안 저장소 또는 로컬 비밀값 저장소 중 사용 가능한 방식으로 안전하게 보관됩니다.</div>
        </div>

        <div class="field" style="margin-bottom:0;">
          <div class="field-row" style="justify-content:flex-end;">
            <button class="btn btn-primary" type="submit">키 저장</button>
          </div>
        </div>
      </form>
    </div>
  </div>
</section>'''

    def _render_activity_item(self, url: str, message: str, success: bool, time_label: str) -> str:
        safe_url = self._escape(url)
        safe_message = self._escape(message)
        return f'''
<li class="activity-item {'fail' if not success else ''}">
  <div class="activity-dot"></div>
  <div>
    <div class="activity-url">{safe_url or '-'}</div>
    <div class="activity-msg">{safe_message}</div>
  </div>
  <div class="activity-time">{self._escape(time_label)}</div>
</li>'''

    def _render_library_row(self, row: dict[str, str]) -> str:
        link = row.get("링크", "")
        prompt = row.get("프롬프트(영문)", "")
        content = row.get("내용", "")
        cameras = parse_camera_parts(row.get("카메라 워킹", ""))
        thumb = detect_source_code(link)
        search_text = " ".join(part for part in [prompt, content, link, " ".join(cameras)] if part)
        camera_attr = "|".join(cameras)
        title = " + ".join(cameras) or (content[:18] if content else "미분류 프롬프트")
        meta = build_row_meta_text(row, cameras)
        link_html = (
            '<span class="meta-link" style="opacity:.7;">생성 초안</span>'
            if thumb == "AI" or not link
            else f'<a class="meta-link" href="{self._escape_attr(link)}" target="_blank" onclick="event.stopPropagation()">열기 →</a>'
        )

        tags_html = "".join(
            f'<button type="button" class="tag" data-filter-camera="{self._escape_attr(camera)}" onclick="event.stopPropagation(); filterByCameraTag(this.dataset.filterCamera)">{self._escape(camera)}</button>'
            for camera in cameras
        ) or '<span class="tag tag-muted">미분류</span>'
        delete_form = f'''
<form method="post" action="/delete" onsubmit="event.stopPropagation(); return confirm('이 항목을 삭제하시겠습니까? 시트에서도 함께 삭제됩니다.');">
  <input type="hidden" name="url" value="{self._escape_attr(link)}">
  <button class="icon-btn" type="submit" title="삭제">
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
  </button>
</form>'''

        return f'''
<tr class="clickable-row" data-search="{self._escape_attr(search_text)}" data-cameras="{self._escape_attr(camera_attr)}" data-title="{self._escape_attr(title)}" data-prompt="{self._escape_attr(prompt)}" data-content="{self._escape_attr(content)}" data-meta="{self._escape_attr(meta)}" data-link="{self._escape_attr(link)}" onclick="openDrawer(this)">
  <td><div class="thumb">{thumb}</div></td>
  <td><div class="tag-row">{tags_html}</div></td>
  <td><div class="prompt-text">{self._escape(prompt)}</div></td>
  <td><div class="content-text">{self._escape(content)}</div></td>
  <td>
    <div class="meta-col">{self._escape(meta)}</div>
    {link_html}
  </td>
  <td class="row-actions">{delete_form}</td>
</tr>'''

    def _build_client_script(self) -> str:
        return r'''
const initialView = document.body.dataset.initialView || 'dashboard';
const views = Array.from(document.querySelectorAll('.view'));
const navItems = Array.from(document.querySelectorAll('.nav-item[data-view]'));

function switchView(name) {
  views.forEach(v => v.classList.toggle('active', v.dataset.view === name));
  navItems.forEach(n => n.classList.toggle('active', n.dataset.view === name));
  const url = new URL(window.location.href);
  url.searchParams.set('view', name);
  history.replaceState({}, '', url.pathname + url.search);
  window.scrollTo({ top: 0, behavior: 'smooth' });
}
window.switchView = switchView;
window.grommyPinnedRefs = [];
function renderPinnedRefs() {
  const hiddenInput = document.getElementById('pinned-refs-input');
  const summaryEl = document.getElementById('pinned-ref-summary');
  if (hiddenInput) hiddenInput.value = JSON.stringify(window.grommyPinnedRefs || []);
  if (!summaryEl) return;
  const refs = window.grommyPinnedRefs || [];
  if (!refs.length) {
    summaryEl.innerHTML = '<span>고정된 레퍼런스 없음</span>';
    return;
  }
  summaryEl.innerHTML = refs.map((ref, idx) => {
    const title = escapeHtml(ref['내용'] || ref['카메라 워킹'] || `레퍼런스 ${idx + 1}`);
    return `<button type="button" class="tag" data-pin-index="${idx}" onclick="removePinnedRef(${idx})">${title} ×</button>`;
  }).join('');
}
window.removePinnedRef = (index) => {
  window.grommyPinnedRefs = (window.grommyPinnedRefs || []).filter((_, idx) => idx !== index);
  renderPinnedRefs();
};
window.setPinnedReferences = (payloads, replace = false) => {
  const next = replace ? [] : [...(window.grommyPinnedRefs || [])];
  for (const payload of (payloads || [])) {
    if (!payload) continue;
    const normalized = {
      '카메라 워킹': payload['카메라 워킹'] || payload.cameras?.join?.(' / ') || '',
      '프롬프트(영문)': payload['프롬프트(영문)'] || payload.prompt || '',
      '내용': payload['내용'] || payload.content || '',
      '링크': payload['링크'] || payload.link || '',
    };
    const key = `${normalized['링크']}|${normalized['내용']}|${normalized['프롬프트(영문)'].slice(0,80)}`;
    if (!next.some(item => `${item['링크']}|${item['내용']}|${item['프롬프트(영문)'].slice(0,80)}` === key)) {
      next.push(normalized);
    }
  }
  window.grommyPinnedRefs = next.slice(0, 5);
  renderPinnedRefs();
};
window.prefillGeneratePrompt = (payload) => {
  const composer = document.querySelector('.assistant-composer .composer-input');
  if (!composer) return;
  switchView('generate');
  const content = (payload?.content || '').trim();
  const prompt = (payload?.prompt || '').trim();
  const cameras = Array.isArray(payload?.cameras) ? payload.cameras.filter(Boolean) : [];
  const parts = [];
  if (content) parts.push(`장면 설명: ${content}`);
  if (cameras.length) parts.push(`원하는 카메라 워킹: ${cameras.join(', ')}`);
  if (prompt) parts.push(`참고 프롬프트:\n${prompt}`);
  composer.value = parts.join('\n\n').trim();
  window.setPinnedReferences([{
    '내용': content,
    '프롬프트(영문)': prompt,
    '카메라 워킹': cameras.join(' / '),
    '링크': payload?.link || '',
  }]);
  composer.dispatchEvent(new Event('input', { bubbles: true }));
  setTimeout(() => composer.focus(), 80);
};
navItems.forEach(item => item.addEventListener('click', () => switchView(item.dataset.view)));
switchView(initialView);
renderPinnedRefs();

// input tabs visual only
Array.from(document.querySelectorAll('.input-tabs .input-tab')).forEach(tab => {
  tab.addEventListener('click', () => {
    if (tab.disabled) return;
    document.querySelectorAll('.input-tabs .input-tab').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
  });
});

// settings nav visual only
Array.from(document.querySelectorAll('.settings-nav-item')).forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.settings-nav-item').forEach(x => x.classList.remove('active'));
    tab.classList.add('active');
  });
});

// run count estimator
const runUrls = document.getElementById('run-urls');
const linkCount = document.querySelector('.link-count');
const costEstimate = document.querySelector('.cost-estimate');
const clearUrls = document.getElementById('clear-urls');
function updateRunEstimate() {
  if (!runUrls || !linkCount || !costEstimate) return;
  const urls = runUrls.value.split(/\n+/).map(v => v.trim()).filter(Boolean);
  const unique = [...new Set(urls)];
  linkCount.textContent = String(unique.length);
  costEstimate.textContent = `약 ${Math.round(unique.length * 4)}원`;
}
if (runUrls) {
  runUrls.addEventListener('input', updateRunEstimate);
  updateRunEstimate();
}
if (clearUrls && runUrls) {
  clearUrls.addEventListener('click', () => {
    runUrls.value = '';
    updateRunEstimate();
    runUrls.focus();
  });
}

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
function normalizeText(value) {
  return (value || '').toLowerCase().replace(/[\s_\-\/]+/g, ' ').trim();
}
function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
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
const searchInput = document.querySelector('.search-input');
const chipsContainer = document.getElementById('library-filter-chips');
const resultsBody = document.getElementById('library-results-body');
function getFilterChips() {
  return Array.from(document.querySelectorAll('.filter-bar .chip[data-camera]'));
}
function getFilterRows() {
  return Array.from(document.querySelectorAll('.results tbody tr[data-search]'));
}
function applyFilters() {
  const query = (searchInput?.value || '').trim();
  const terms = query ? query.split(/\s+/).filter(Boolean) : [];
  const activeCameras = getFilterChips().filter(chip => chip.classList.contains('active')).map(chip => normalizeText(chip.dataset.camera || ''));
  getFilterRows().forEach(row => {
    const haystack = normalizeText(row.dataset.search || '');
    const rowCameras = (row.dataset.cameras || '').split('|').map(normalizeText).filter(Boolean);
    const queryMatch = terms.every(term => expandToken(term).some(candidate => haystack.includes(candidate)));
    const cameraMatch = !activeCameras.length || activeCameras.some(camera => rowCameras.includes(camera));
    row.style.display = (queryMatch && cameraMatch) ? '' : 'none';
  });
}
function bindChipEvents() {
  getFilterChips().forEach(chip => {
    if (chip.dataset.bound === '1') return;
    chip.dataset.bound = '1';
    chip.addEventListener('click', () => {
      chip.classList.toggle('active');
      applyFilters();
    });
  });
}
if (searchInput) searchInput.addEventListener('input', applyFilters);
const resetFilters = document.getElementById('reset-filters');
if (resetFilters) {
  resetFilters.addEventListener('click', () => {
    if (searchInput) searchInput.value = '';
    getFilterChips().forEach(chip => chip.classList.remove('active'));
    applyFilters();
  });
}
window.filterByCameraTag = (camera) => {
  getFilterChips().forEach(chip => chip.classList.toggle('active', normalizeText(chip.dataset.camera || '') === normalizeText(camera)));
  applyFilters();
  switchView('library');
};
bindChipEvents();
applyFilters();

function renderLibraryRow(row) {
  const link = row['링크'] || '';
  const prompt = row['프롬프트(영문)'] || '';
  const content = row['내용'] || '';
  const cameras = (row['카메라 워킹'] || '').split('/').map(v => v.trim()).filter(Boolean);
  const rowMeta = row['__meta'] || {};
  const thumb = link.toLowerCase().includes('instagram.com') ? 'IG' : (link.toLowerCase().includes('youtube.com') || link.toLowerCase().includes('youtu.be') ? 'YT' : 'WEB');
  const isGenerated = link.toLowerCase().startsWith('grommy://generated/');
  const realThumb = isGenerated ? 'AI' : thumb;
  const sourceLabel = realThumb === 'IG' ? 'Instagram' : (realThumb === 'YT' ? 'YouTube' : (realThumb === 'AI' ? 'AI Draft' : 'Web'));
  const searchText = [prompt, content, link, cameras.join(' ')].filter(Boolean).join(' ');
  const cameraAttr = cameras.join('|');
  const title = cameras.join(' + ') || (content ? content.slice(0, 18) : '미분류 프롬프트');
  const metaParts = [sourceLabel, cameras.length ? ('카메라 ' + cameras.join(', ')) : '미분류'];
  if (Array.isArray(rowMeta.source_refs) && rowMeta.source_refs.length) {
    metaParts.push(`참조 ${rowMeta.source_refs.length}개`);
  }
  if (rowMeta.source === 'extract' && rowMeta.warning) {
    metaParts.push('부분 보정');
  }
  const meta = metaParts.join(' · ');
  const tagsHtml = cameras.length
    ? cameras.map(camera => `<button type="button" class="tag" data-filter-camera="${escapeHtml(camera)}" onclick="event.stopPropagation(); filterByCameraTag(this.dataset.filterCamera)">${escapeHtml(camera)}</button>`).join('')
    : '<span class="tag tag-muted">미분류</span>';
  const linkHtml = (isGenerated || !link)
    ? '<span class="meta-link" style="opacity:.7;">생성 초안</span>'
    : `<a class="meta-link" href="${escapeHtml(link)}" target="_blank" onclick="event.stopPropagation()">열기 →</a>`;
  return `<tr class="clickable-row" data-search="${escapeHtml(searchText)}" data-cameras="${escapeHtml(cameraAttr)}" data-title="${escapeHtml(title)}" data-prompt="${escapeHtml(prompt)}" data-content="${escapeHtml(content)}" data-meta="${escapeHtml(meta)}" data-link="${escapeHtml(link)}" onclick="openDrawer(this)">
  <td><div class="thumb">${realThumb}</div></td>
  <td><div class="tag-row">${tagsHtml}</div></td>
  <td><div class="prompt-text">${escapeHtml(prompt)}</div></td>
  <td><div class="content-text">${escapeHtml(content)}</div></td>
  <td><div class="meta-col">${escapeHtml(meta)}</div>${linkHtml}</td>
  <td class="row-actions">
    <form method="post" action="/delete" onsubmit="event.stopPropagation(); return confirm('이 항목을 삭제하시겠습니까? 시트에서도 함께 삭제됩니다.');">
      <input type="hidden" name="url" value="${escapeHtml(link)}">
      <button class="icon-btn" type="submit" title="삭제">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
      </button>
    </form>
  </td>
  </tr>`;
}

function renderLibraryChips(cameraCounts) {
  if (!chipsContainer) return;
  chipsContainer.innerHTML = cameraCounts.length
    ? cameraCounts.map(([camera, count]) => `<button class="chip" type="button" data-camera="${escapeHtml(camera)}">${escapeHtml(camera)} <span class="count">${count}</span></button>`).join('')
    : '<span class="muted">아직 카메라 워킹 데이터가 없습니다.</span>';
  bindChipEvents();
}

async function refreshLibraryState() {
  if (!resultsBody) return;
  try {
    const response = await fetch('/api/library', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();
    resultsBody.innerHTML = Array.isArray(data.rows) && data.rows.length
      ? data.rows.map(renderLibraryRow).join('')
      : '<tr><td colspan="6" class="empty">아직 저장된 결과가 없습니다.</td></tr>';
    renderLibraryChips(Array.isArray(data.camera_counts) ? data.camera_counts : []);
    applyFilters();
  } catch (_err) {
    // ignore refresh errors
  }
}

function renderActivityItem(item, indexLabel) {
  return `<li class="activity-item ${item.success ? '' : 'fail'}">
    <div class="activity-dot"></div>
    <div>
      <div class="activity-url">${escapeHtml(item.url || '-')}</div>
      <div class="activity-msg">${escapeHtml(item.message || '')}</div>
    </div>
    <div class="activity-time">${escapeHtml(indexLabel)}</div>
  </li>`;
}

async function refreshRuntimeState() {
  try {
    const response = await fetch('/api/state', { cache: 'no-store' });
    if (!response.ok) return;
    const data = await response.json();

    const resultsCountEl = document.getElementById('metric-results-count');
    if (resultsCountEl) resultsCountEl.textContent = String(data.results_count ?? 0);
    const successRateEl = document.getElementById('metric-success-rate');
    if (successRateEl) successRateEl.textContent = `${data.success_rate ?? 0}%`;
    const sessionCostEl = document.getElementById('metric-session-cost');
    if (sessionCostEl) sessionCostEl.textContent = `₩${Math.round(data.current_session_cost ?? 0)}`;

    const topCameraRows = Array.from(document.querySelectorAll('.top-camera-row'));
    if (topCameraRows.length && Array.isArray(data.top_cameras)) {
      topCameraRows.forEach((row, idx) => {
        const item = data.top_cameras[idx];
        if (!item) {
          row.style.display = 'none';
          return;
        }
        row.style.display = '';
        const [cameraName, count] = item;
        const maxCount = data.top_cameras[0] ? data.top_cameras[0][1] : 1;
        const nameEl = row.querySelector('.top-camera-name');
        const countEl = row.querySelector('.top-camera-count');
        const barEl = row.querySelector('.top-camera-bar');
        if (nameEl) nameEl.textContent = cameraName;
        if (countEl) countEl.textContent = String(count);
        if (barEl) barEl.style.width = `${Math.max(12, Math.round((count / maxCount) * 100))}%`;
      });
    }

    const badgeEl = document.getElementById('run-badge');
    if (badgeEl) badgeEl.textContent = data.running ? '실행 중' : '대기 중';
    const fillEl = document.getElementById('run-progress-fill');
    if (fillEl) {
      const width = !data.total ? 0 : Math.round((data.completed / data.total) * 100);
      fillEl.style.width = `${width}%`;
    }
    const progressTextEl = document.getElementById('run-progress-text');
    if (progressTextEl) progressTextEl.innerHTML = `<strong style="color:var(--ink); font-weight:700;">${data.completed ?? 0}</strong> / ${data.total ?? 0} 완료`;
    const summaryEl = document.getElementById('run-progress-summary');
    if (summaryEl) summaryEl.textContent = data.summary || '';
    const statusLineEl = document.getElementById('run-status-line');
    if (statusLineEl) statusLineEl.textContent = `${data.status || ''} · ${data.summary || ''}`;
    const activityListEl = document.getElementById('run-activity-list');
    if (activityListEl && Array.isArray(data.items)) {
      activityListEl.innerHTML = data.items.length
        ? data.items.map((item, idx) => renderActivityItem(item, `${idx + 1}건`)).join('')
        : '<li class="activity-item"><div><div class="activity-msg">아직 실행된 작업이 없습니다. 링크를 넣고 시작하면 이곳에 진행 내역이 쌓입니다.</div></div></li>';
    }
  } catch (_err) {
    // ignore polling errors
  }
}

setInterval(refreshRuntimeState, 2000);
refreshRuntimeState();
setInterval(refreshLibraryState, 5000);
refreshLibraryState();

const drawerEl = document.querySelector('.drawer');
const overlayEl = document.querySelector('.drawer-overlay');
window.openDrawer = (row) => {
  if (!drawerEl || !overlayEl) return;
  const title = row.dataset.title || '프롬프트 상세';
  const prompt = row.dataset.prompt || '';
  const content = row.dataset.content || '';
  const meta = row.dataset.meta || '';
  const link = row.dataset.link || '';
  const cameras = (row.dataset.cameras || '').split('|').filter(Boolean);
  const thumb = row.querySelector('.thumb')?.textContent || 'IG';
  const isGenerated = link.toLowerCase().startsWith('grommy://generated/');
  drawerEl.dataset.prompt = prompt;
  drawerEl.dataset.content = content;
  drawerEl.dataset.cameras = cameras.join('|');

  drawerEl.querySelector('.drawer-thumb').textContent = thumb;
  drawerEl.querySelector('.drawer-title').textContent = title;
  drawerEl.querySelector('.drawer-sub').textContent = meta;
  const tagRow = drawerEl.querySelector('.tag-row');
  tagRow.innerHTML = cameras.length ? cameras.map(camera => `<span class="tag">${camera}</span>`).join('') : '<span class="tag tag-muted">미분류</span>';
  const contentBox = drawerEl.querySelectorAll('.drawer-body > div')[2]?.querySelector('div:last-child');
  if (contentBox) contentBox.textContent = content || '내용 정보가 없습니다.';
  const promptBox = drawerEl.querySelector('.drawer-prompt');
  promptBox.innerHTML = '<button class="copy-btn">복사</button>' + (prompt || '프롬프트가 없습니다.');
  const openBtn = drawerEl.querySelector('.drawer-footer [data-action="open"]');
  const copyBtn = drawerEl.querySelector('.drawer-footer [data-action="copy"]');
  const pinBtn = drawerEl.querySelector('.drawer-footer [data-action="pin"]');
  const regroomBtn = drawerEl.querySelector('.drawer-footer [data-action="regroom"]');
  if (openBtn) {
    if (isGenerated || !link) {
      openBtn.textContent = '생성 초안';
      openBtn.setAttribute('onclick', 'return false;');
      openBtn.setAttribute('disabled', 'disabled');
    } else {
      openBtn.textContent = '원본 링크 열기';
      openBtn.removeAttribute('disabled');
      openBtn.setAttribute('onclick', `window.open('${link.replace(/'/g, "%27")}', '_blank')`);
    }
  }
  if (copyBtn) {
    copyBtn.removeAttribute('disabled');
    copyBtn.setAttribute('onclick', `navigator.clipboard?.writeText(${JSON.stringify(prompt || '')}); return false;`);
  }
  if (pinBtn) {
    pinBtn.removeAttribute('disabled');
    pinBtn.setAttribute(
      'onclick',
      `setPinnedReferences([{` +
      `"내용":${JSON.stringify(content || '')},` +
      `"카메라 워킹":${JSON.stringify(cameras.join(' / '))},` +
      `"프롬프트(영문)":${JSON.stringify(prompt || '')},` +
      `"링크":${JSON.stringify(link || '')}` +
      `}]); switchView('generate'); closeDrawer(); return false;`
    );
  }
  if (regroomBtn) {
    regroomBtn.removeAttribute('disabled');
    regroomBtn.setAttribute(
      'onclick',
      `prefillGeneratePrompt({content:${JSON.stringify(content || '')},prompt:${JSON.stringify(prompt || '')},cameras:${JSON.stringify(cameras)},link:${JSON.stringify(link || '')}}); closeDrawer(); return false;`
    );
  }

  drawerEl.classList.add('open');
  overlayEl.classList.add('open');
  document.body.style.overflow = 'hidden';
};
window.closeDrawer = () => {
  if (!drawerEl || !overlayEl) return;
  drawerEl.classList.remove('open');
  overlayEl.classList.remove('open');
  document.body.style.overflow = '';
};
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeDrawer(); });

document.addEventListener('click', (e) => {
  if (e.target.classList.contains('copy-btn')) {
    e.stopPropagation();
    const text = e.target.parentElement.textContent.replace('복사', '').trim();
    navigator.clipboard?.writeText(text);
    const original = e.target.textContent;
    e.target.textContent = '✓ 복사됨';
    setTimeout(() => { e.target.textContent = original; }, 1200);
  }
});
'''

    def serve_file(self, path: Path, content_type: str) -> None:
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{path.name}"')
        self.end_headers()
        self.safe_write(path.read_bytes())

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


def run_server(host: str, port: int, open_browser: bool = False) -> None:
    server = ThreadingHTTPServer((host, port), PromptExtractorHandler)
    url = f"http://{host}:{port}" if host != "0.0.0.0" else f"http://127.0.0.1:{port}"
    public_url = get_public_base_url()
    deployment = build_deployment_status(extract.load_config())
    print(f"PromptExtractor 웹 서버 실행 중: {url}")
    if public_url:
        print(f"공개 주소 감지: {public_url}")
    print(
        "배포 준비 상태:"
        f" Gemini={'OK' if deployment['gemini_ready'] else 'MISSING'}"
        f" Sheets={'OK' if deployment['sheets_ready'] else 'MISSING'}"
        f" Outputs={deployment['outputs_dir']}"
    )
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
    parser.add_argument("--host", default=__import__('os').environ.get('PROMPT_EXTRACTOR_HOST', '0.0.0.0'))
    parser.add_argument("--port", type=int, default=int(__import__('os').environ.get('PORT', '5001')))
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()
    run_server(args.host, args.port, open_browser=args.open_browser)


if __name__ == "__main__":
    main()
