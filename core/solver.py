"""규칙을 지키는 팀 배정을 '완전 탐색(백트래킹)'으로 찾는 모듈.

완전 탐색이란? 가능한 배정을 하나씩 모두 시도해 보는 방법입니다.
그냥 다 해 보면 너무 오래 걸리므로, '이미 규칙을 어겼거나 앞으로 절대 맞출 수 없는 상태'는
중간에 바로 버립니다(가지치기). 가지치기는 '확실히 불가능한 경우'만 버리기 때문에
탐색이 끝까지 돌았는데 해가 없다면, 정말로 규칙에 맞는 배정이 없다는 뜻입니다(status="infeasible").
제한 시간 안에 끝내지 못하면 "limit" 으로 정직하게 알립니다.

(이 파일은 AI를 쓰지 못할 때의 최후 수단이면서, 'AI가 틀렸는지' 판단하는 기준 역할도 합니다.)

탐색 순서: 매 단계마다 '들어갈 수 있는 팀이 가장 적은 학생'부터 배정합니다(막다른 길을 빨리 발견).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from core import rules
from core.rules import MAX_TEAM_SIZE, MIN_TEAM_SIZE


@dataclass
class SolveResult:
    status: str          # "found" | "infeasible" | "limit"
    assignment: dict     # {student_no: team_id}  (팀이 없던 학생들만)
    nodes: int           # 탐색한 상태 수
    solutions: int       # 찾은 해의 개수 (상한까지만 셈)
    message: str
    reasons: list = field(default_factory=list)   # 해가 없을 때 그 이유 (사람이 읽는 문장)


def diagnose(teams: dict, free: list) -> list:
    """규칙을 지키는 배정이 없을 때, 눈에 보이는 원인을 문장으로 설명합니다.
    (원인 후보를 하나씩 점검하는 것이며, 못 찾아도 '해가 없다'는 결론 자체는 탐색 결과가 보장합니다.)"""
    reasons = []
    ids = sorted(teams)
    n_teams = len(ids)
    existing = [m for t in ids for m in teams[t]]
    total = len(existing) + len(free)
    if n_teams == 0:
        return ["만들어진 팀이 없습니다."]
    if total < MIN_TEAM_SIZE * n_teams:
        reasons.append(f"전체 학생이 {total}명이라 {n_teams}개 팀을 모두 {MIN_TEAM_SIZE}명 이상으로 채울 수 없습니다.")
    if total > MAX_TEAM_SIZE * n_teams:
        reasons.append(f"전체 학생이 {total}명이라 {n_teams}개 팀(팀당 최대 {MAX_TEAM_SIZE}명)에 모두 들어갈 수 없습니다.")

    by_role: dict = {}
    for m in existing + list(free):
        by_role.setdefault(m.main_key, []).append(m)
    for group in by_role.values():
        if len(group) > n_teams:
            reasons.append(f"주 역할 '{group[0].main_role}' 학생이 {len(group)}명인데 팀은 {n_teams}개뿐이라 "
                           f"같은 주 역할이 한 팀에 모이지 않게 나눌 수 없습니다.")

    for t in ids:
        for e in rules.team_errors(teams[t], check_size=False):
            reasons.append(f"{t}번 팀(기존 팀원 {len(teams[t])}명): {e}")

    for s in free:
        if all(rules.join_blocker(teams[t], s) for t in ids):
            reasons.append(f"{s.name}({s.student_no}) 학생은 어느 팀에도 들어갈 수 없습니다 "
                           f"(정원 초과, 같은 주 역할 팀원 존재, 또는 필수 역할을 갖출 수 없게 됨).")

    no_plan = sum(1 for t in ids if not any(x.can_plan for x in teams[t]))
    no_web = sum(1 for t in ids if not any(x.can_web for x in teams[t]))
    avail_plan = sum(1 for s in free if s.can_plan)
    avail_web = sum(1 for s in free if s.can_web)
    if no_plan > avail_plan:
        reasons.append(f"'{rules.PLANNER_ROLE}'를 맡을 사람이 아직 없는 팀이 {no_plan}개인데, "
                       f"배정할 학생 중 맡을 수 있는 학생은 {avail_plan}명뿐입니다.")
    if no_web > avail_web:
        reasons.append(f"'{rules.WEB_ROLE}'를 맡을 사람이 아직 없는 팀이 {no_web}개인데, "
                       f"배정할 학생 중 맡을 수 있는 학생은 {avail_web}명뿐입니다.")
    gap_total = sum(2 - rules.role_coverage(teams[t]) for t in ids)
    avail_any = sum(1 for s in free if s.can_plan or s.can_web)
    if gap_total > avail_any:
        reasons.append(f"모든 팀에 기획자·웹 프로그래머를 서로 다른 사람으로 갖추려면 역할을 맡을 수 있는 학생이 "
                       f"최소 {gap_total}명 더 필요한데, 배정할 학생 중에는 {avail_any}명뿐입니다.")
    return reasons


def solve(teams: dict, free: list, max_solutions: int = 30, max_seconds: float = 15.0) -> SolveResult:
    """teams = {team_id: [기존 팀원 Student...]} (빈 팀 포함), free = 팀이 없는 Student 목록.

    규칙을 모두 지키는 배정이 있으면 그중 인원이 가장 고른 것을 돌려줍니다.
    """
    team_ids = sorted(teams)
    members = {t: list(teams[t]) for t in team_ids}

    # 기존 팀이 이미 규칙을 어기고 있으면 어떤 배정을 해도 해결할 수 없음
    for t in team_ids:
        errs = rules.team_errors(members[t], check_size=False)
        if errs:
            return SolveResult("infeasible", {}, 0, 0, "규칙을 지키는 배정이 없음",
                               [f"{t}번 팀이 이미 규칙을 어기고 있어 어떤 배정으로도 고칠 수 없습니다: {errs[0]}"]
                               + [r for r in diagnose(teams, free) if f"{t}번 팀" not in r])

    unplaced = sorted(free, key=lambda s: s.student_no)
    solutions: list = []
    assign: dict = {}
    state = {"nodes": 0, "timeout": False}
    start = time.monotonic()

    def bound_ok() -> bool:
        """가지치기: 남은 학생들로 모든 팀을 규칙에 맞게 채울 '가능성'이 있는가?
        (불가능이 확실할 때만 False 를 돌려주므로 해를 놓치지 않습니다.)"""
        remaining = len(unplaced)
        total_need = capacity = role_need = no_plan = no_web = 0
        for t in team_ids:
            m = members[t]
            size = len(m)
            room = MAX_TEAM_SIZE - size
            gap = 2 - rules.role_coverage(m)          # 기획/웹 자리를 채우려면 역할 가능 학생이 최소 gap 명 필요
            need = max(MIN_TEAM_SIZE - size, gap, 0)   # 앞으로 최소 필요한 인원
            if need > room:
                return False
            total_need += need
            role_need += gap
            capacity += room
            no_plan += 0 if any(x.can_plan for x in m) else 1
            no_web += 0 if any(x.can_web for x in m) else 1
        if not (total_need <= remaining <= capacity):
            return False
        if (role_need > sum(1 for s in unplaced if s.can_plan or s.can_web)
                or no_plan > sum(1 for s in unplaced if s.can_plan)
                or no_web > sum(1 for s in unplaced if s.can_web)):
            return False
        # 같은 주 역할 학생 k명은 서로 다른 팀에 들어가야 하므로, 그 역할이 없고 자리가 남은 팀이 k개 이상 있어야 함
        role_left = {}
        for s in unplaced:
            role_left[s.main_key] = role_left.get(s.main_key, 0) + 1
        for key, count in role_left.items():
            open_teams = sum(1 for t in team_ids
                             if len(members[t]) < MAX_TEAM_SIZE and all(x.main_key != key for x in members[t]))
            if count > open_teams:
                return False
        return True

    def dfs() -> None:
        if state["timeout"] or len(solutions) >= max_solutions:
            return
        state["nodes"] += 1
        if state["nodes"] % 200 == 0 and time.monotonic() - start > max_seconds:
            state["timeout"] = True
            return
        if not bound_ok():
            return
        if not unplaced:
            if all(not rules.team_errors(members[t]) for t in team_ids):
                solutions.append(dict(assign))
            return

        # 들어갈 수 있는 팀이 가장 적은 학생을 고른다 (0개면 그 즉시 막다른 길)
        best_idx, best_opts = -1, None
        for idx, s in enumerate(unplaced):
            opts = [t for t in team_ids if rules.join_blocker(members[t], s) is None]
            if not opts:
                return
            if best_opts is None or len(opts) < len(best_opts):
                best_idx, best_opts = idx, opts
                if len(opts) == 1:
                    break
        s = unplaced.pop(best_idx)
        tried_empty = False
        # 인원이 적은 팀부터 시도 -> 고른 해가 먼저 나옵니다.
        for t in sorted(best_opts, key=lambda x: (len(members[x]), x)):
            m = members[t]
            if not m:
                if tried_empty:        # 빈 팀끼리는 서로 똑같으므로 하나만 시도 (대칭 제거)
                    continue
                tried_empty = True
            m.append(s)
            assign[s.student_no] = t
            dfs()
            m.pop()
            del assign[s.student_no]
        unplaced.insert(best_idx, s)

    dfs()

    if solutions:
        base = {t: len(members[t]) for t in team_ids}

        def score(sol):
            sizes = dict(base)
            for team_id in sol.values():
                sizes[team_id] += 1
            return sum(v * v for v in sizes.values())

        best = min(solutions, key=score)
        return SolveResult("found", best, state["nodes"], len(solutions),
                           f"규칙을 지키는 배정을 찾았습니다. (탐색 {state['nodes']:,}회)")
    if state["timeout"]:
        return SolveResult("limit", {}, state["nodes"], 0,
                           f"제한 시간({max_seconds:.0f}초) 안에 결론을 내지 못했습니다. "
                           f"(규칙을 어기는 배정은 확정하지 않습니다)",
                           ["탐색이 오래 걸려 중단했습니다. 해가 없다는 뜻은 아닙니다. 팀 수나 명단을 조정해 다시 시도해 보세요."])
    reasons = diagnose(teams, free) or [
        "개별 원인 하나로 설명되지는 않지만, 가능한 모든 배정을 따져 본 결과 "
        "역할 조합이 서로 충돌해 모든 규칙을 동시에 만족하는 경우가 없습니다."]
    return SolveResult("infeasible", {}, state["nodes"], 0, "규칙을 지키는 배정이 없음", reasons)
