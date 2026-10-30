"""OpenRouter AI 팀 배정 모듈.

흐름: 프롬프트 만들기 -> 모델 호출 -> JSON 파싱 -> 규칙 검사 -> (통과해야만) 채택
AI의 답은 '제안'일 뿐입니다. 아래 validate_ai_assignment() 의 모든 검사를 통과하지 못하면
그 모델의 답은 버리고 다음 모델로 넘어갑니다.

개인정보 보호: AI에게는 이름 없이 학번과 역할만 보냅니다.
"""
from __future__ import annotations

import json
import re

import requests

from core import rules
from core.rules import Student

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_TIMEOUT_SECONDS = 120   # 모델 한 개당 호출 제한 시간 (과제 공고 기준)
MAX_MODELS = 3             # 순서대로 시도할 최대 모델 수


def build_messages(teams: dict, free: list) -> list:
    """teams = {team_id: [기존 팀원]}, free = 팀이 없는 학생들."""
    def pack(s: Student) -> dict:
        return {"student_no": s.student_no, "main_role": s.main_role, "sub_roles": list(s.sub_roles)}

    data = {
        "teams": [{"team_id": t, "current_members": [pack(m) for m in teams[t]]} for t in sorted(teams)],
        "unassigned_students": [pack(s) for s in free],
    }
    system = "당신은 팀 편성 도우미입니다. 반드시 JSON 객체 하나만 출력하고, 설명 문장이나 마크다운은 쓰지 않습니다."
    user = f"""아래 '팀이 없는 학생'을 모두 팀에 배정하세요. 기존 팀원은 옮기지 않습니다.

[반드시 지킬 규칙]
1. 모든 팀의 최종 인원은 {rules.MIN_TEAM_SIZE}~{rules.MAX_TEAM_SIZE}명 (기존 팀원 포함, 비어 있는 팀도 채워야 함)
2. 한 팀에 주 역할(main_role)이 같은 학생이 2명 이상 있으면 안 됨
3. 모든 팀에는 '{rules.PLANNER_ROLE}' 역할을 맡을 수 있는 학생 1명과 '{rules.WEB_ROLE}' 역할을 맡을 수 있는 학생 1명이 있어야 하며, 두 사람은 서로 다른 사람이어야 함 (main_role 과 sub_roles 모두 인정)
4. 모든 unassigned_students 는 정확히 한 팀에만 배정

[출력 형식 - 이 JSON 형식만 출력]
{{"assignments": [{{"student_no": "학번", "team_id": 팀번호}}, ...]}}

[데이터]
{json.dumps(data, ensure_ascii=False)}"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def extract_json(text: str):
    """모델 답변에서 JSON 객체를 꺼냅니다. (```json 코드블록이나 앞뒤 설명이 붙어도 처리)"""
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def validate_ai_assignment(text: str, teams: dict, free: list, team_names: dict | None = None):
    """AI 답변을 엄격하게 검사합니다. (배정 dict 또는 None, 오류 목록)을 돌려줍니다.
    오류가 하나라도 있으면 배정은 None 입니다 -> 승인하지 않음."""
    try:
        parsed = extract_json(text)
    except (json.JSONDecodeError, ValueError):
        return None, ["JSON 형식이 아닙니다."]

    items = parsed.get("assignments") if isinstance(parsed, dict) else None
    if isinstance(items, dict):  # {"학번": 팀번호} 형태도 허용
        items = [{"student_no": k, "team_id": v} for k, v in items.items()]
    if not isinstance(items, list):
        return None, ["'assignments' 목록이 없습니다."]

    free_map = {s.student_no: s for s in free}
    assignment, errors = {}, []
    for item in items:
        if not isinstance(item, dict):
            errors.append("assignments 항목 형식이 잘못되었습니다.")
            continue
        no = str(item.get("student_no", "")).strip()
        raw_team = item.get("team_id")
        if isinstance(raw_team, bool):
            errors.append(f"{no}: team_id 가 숫자가 아닙니다.")
            continue
        try:
            team_id = int(raw_team)
        except (TypeError, ValueError):
            errors.append(f"{no}: team_id 가 숫자가 아닙니다.")
            continue
        if no not in free_map:
            errors.append(f"{no}: 배정 대상이 아닌 학번입니다(존재하지 않거나 이미 팀이 있음).")
            continue
        if team_id not in teams:
            errors.append(f"{no}: 존재하지 않는 팀 번호 {team_id} 입니다.")
            continue
        if no in assignment:
            errors.append(f"{no}: 두 번 이상 배정되었습니다.")
            continue
        assignment[no] = team_id

    missing = [no for no in free_map if no not in assignment]
    if missing:
        errors.append(f"배정되지 않은 학생이 있습니다: {', '.join(missing)}")
    if errors:
        return None, errors

    final = {t: list(teams[t]) for t in teams}
    for no, team_id in assignment.items():
        final[team_id].append(free_map[no])
    rule_errors = rules.validate_assignment(final, team_names)
    if rule_errors:
        return None, rule_errors
    return assignment, []


def call_openrouter(api_key: str, model: str, messages: list, timeout: int = AI_TIMEOUT_SECONDS) -> str:
    """OpenRouter 에 한 번 요청합니다. 120초 안에 응답이 없으면 requests.Timeout 이 발생합니다."""
    response = requests.post(
        OPENROUTER_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def describe_failure(error: Exception) -> str:
    """실패 원인을 짧게 설명합니다. (API 키 같은 민감한 정보는 넣지 않음)"""
    if isinstance(error, requests.Timeout):
        return f"{AI_TIMEOUT_SECONDS}초 안에 응답이 없음(시간 초과)"
    if isinstance(error, requests.HTTPError) and error.response is not None:
        return f"HTTP 오류 {error.response.status_code}"
    if isinstance(error, requests.ConnectionError):
        return "네트워크 연결 실패"
    if isinstance(error, (KeyError, IndexError, TypeError, ValueError)):
        return "응답 형식이 예상과 다름"
    return type(error).__name__


def run_ai_assignment(api_key, models, teams, free, team_names=None, caller=call_openrouter):
    """모델을 순서대로(최대 3개) 시도합니다.
    성공하면 (배정, 모델이름, 로그), 모두 실패하면 (None, None, 로그)."""
    logs = []
    if not api_key:
        return None, None, ["OPENROUTER_API_KEY 가 설정되지 않아 AI 배정을 건너뜁니다."]
    if not models:
        return None, None, ["OPENROUTER_MODELS 가 설정되지 않아 AI 배정을 건너뜁니다."]
    messages = build_messages(teams, free)
    for model in models[:MAX_MODELS]:
        try:
            answer = caller(api_key, model, messages)
        except Exception as e:  # 시간 초과, 네트워크 오류, 인증 오류, 응답 형식 오류 등 -> 다음 모델로
            logs.append(f"[{model}] 호출 실패 -> 다음 모델: {describe_failure(e)}")
            continue
        if not isinstance(answer, str) or not answer.strip():
            logs.append(f"[{model}] 빈 응답 -> 실패 처리, 다음 모델")
            continue
        assignment, errors = validate_ai_assignment(answer, teams, free, team_names)
        if assignment is not None:
            logs.append(f"[{model}] 규칙 검사 통과 -> 채택")
            return assignment, model, logs
        logs.append(f"[{model}] 규칙 검사 실패 -> 폐기: " + " / ".join(errors[:3]))
    return None, None, logs
