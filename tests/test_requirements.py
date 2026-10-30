"""과제 요구사항(지원/투표/마감/AI/권한/DB 이름)을 하나씩 확인하는 테스트."""
import json
import re
import unittest
from pathlib import Path
from unittest import mock

import requests

from core import ai_assigner, rules, services
from tests.fake_repo import FakeRepo
from tests.test_core import ADMIN, ST, roster

ROOT = Path(__file__).resolve().parent.parent


def make_repo(students, teams):
    repo = FakeRepo()
    services.initialize(repo, ADMIN, students, teams)
    return repo


def stu(no, role, subs=()):
    return {"student_no": str(no), "name": f"학생{no}", "main_role": role, "sub_roles": list(subs)}


class ApplyVoteRulesTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo(roster(), 4)

    def test_empty_team_instant_approval_is_stored(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        app = self.repo.list_applications(student_no="20001")[0]
        self.assertEqual(app["status"], "approved")
        self.assertEqual(self.repo.members["20001"], 1)

    def test_one_pending_application_at_a_time(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        services.apply_to_team(self.repo, ST("20004"), 1)             # 대기
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20004"), 2)         # 결과 나오기 전 다른 팀 지원 불가
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20001"), 2)         # 이미 팀 소속

    def test_all_members_must_approve_and_votes_are_saved(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        services.apply_to_team(self.repo, ST("20004"), 1)
        a = self.repo.list_applications(status="pending")[0]["id"]
        services.cast_vote(self.repo, ST("20001"), a, True)           # 20004 합류 (팀원 1명 전원 찬성)
        services.apply_to_team(self.repo, ST("20007"), 1)
        b = self.repo.list_applications(status="pending")[0]["id"]
        self.assertEqual(services.cast_vote(self.repo, ST("20004"), b, True)["status"], "pending")  # 아직 1명 남음
        self.assertEqual(self.repo.get_application(b)["status"], "pending")
        self.assertEqual(services.cast_vote(self.repo, ST("20001"), b, True)["status"], "approved")
        self.assertEqual({v["voter_no"]: v["vote"] for v in self.repo.list_votes(b)},
                         {"20004": "approve", "20001": "approve"})

    def test_single_reject_is_immediate(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        services.apply_to_team(self.repo, ST("20004"), 1)
        a = self.repo.list_applications(status="pending")[0]["id"]
        services.cast_vote(self.repo, ST("20001"), a, True)
        services.apply_to_team(self.repo, ST("20007"), 1)
        b = self.repo.list_applications(status="pending")[0]["id"]
        res = services.cast_vote(self.repo, ST("20004"), b, False)     # 20001 은 아직 투표 안 했지만 즉시 거절
        self.assertEqual(res["status"], "rejected")
        self.assertNotIn("20007", self.repo.members)

    def test_after_close_no_apply_no_vote_and_close_effects(self):
        services.apply_to_team(self.repo, ST("20001"), 1)             # 1팀 1명
        services.apply_to_team(self.repo, ST("20004"), 2)             # 2팀 1명
        services.apply_to_team(self.repo, ST("20007"), 3)             # 3팀 1명
        services.apply_to_team(self.repo, ST("20011"), 1)             # 1팀에 대기
        services.apply_to_team(self.repo, ST("20015"), 2)             # 2팀에 대기
        pending_ids = [a["id"] for a in self.repo.list_applications(status="pending")]
        self.assertEqual(len(pending_ids), 2)
        services.close_recruitment(self.repo, ADMIN)
        for pid in pending_ids:
            self.assertEqual(self.repo.get_application(pid)["status"], "rejected")
        self.assertEqual(self.repo.list_members(), [])                # 모두 1명뿐인 팀이었으므로 전원 제거
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20012"), 1)
        with self.assertRaises(services.ServiceError):
            services.cast_vote(self.repo, ST("20001"), pending_ids[0], True)

    def test_team_with_two_or_more_is_kept_on_close(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        services.apply_to_team(self.repo, ST("20004"), 1)
        a = self.repo.list_applications(status="pending")[0]["id"]
        services.cast_vote(self.repo, ST("20001"), a, True)
        services.apply_to_team(self.repo, ST("20007"), 2)             # 1명짜리 팀
        info = services.close_recruitment(self.repo, ADMIN)
        self.assertEqual(sorted(self.repo.members), ["20001", "20004"])
        self.assertEqual(info["released"], ["학생7"])


class JoinCheckTest(unittest.TestCase):
    """지원할 때, 그리고 승인 직전에 인원 / 주 역할 중복 / 필수 역할을 확인한다."""

    def setUp(self):
        self.repo = make_repo([
            stu(1, "기획자"), stu(2, "디자이너"), stu(3, "분석가"),
            stu(4, "발표자"), stu(5, "웹 프로그래머"), stu(6, "마케터"), stu(7, "디자이너")], 2)

    def team_up(self, nos, team=1):
        for no in nos:
            services.apply_to_team(self.repo, ST(no), team)
            pending = self.repo.list_applications(student_no=str(no), status="pending")
            if pending:
                for m in [n for n, t in self.repo.members.items() if t == team]:
                    if self.repo.get_application(pending[0]["id"])["status"] == "pending":
                        services.cast_vote(self.repo, ST(m), pending[0]["id"], True)

    def test_required_role_lookahead_blocks_unfixable_team(self):
        self.team_up([1, 2, 3])                                       # 기획자·디자이너·분석가: 웹 담당 없음, 3명
        with self.assertRaises(services.ServiceError) as ctx:
            services.apply_to_team(self.repo, ST(4), 1)               # 발표자는 웹을 못 함 -> 4명이 되어도 규칙 불가
        self.assertIn("웹 프로그래머", str(ctx.exception))
        services.apply_to_team(self.repo, ST(5), 1)                   # 웹 프로그래머는 지원 가능
        self.assertEqual(self.repo.list_applications(student_no="5")[0]["status"], "pending")

    def test_duplicate_main_role_blocked_at_apply(self):
        self.team_up([2])
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST(7), 1)               # 같은 주 역할(디자이너)

    def test_full_team_blocked(self):
        self.team_up([1, 5, 2, 3])
        self.assertEqual(len([n for n, t in self.repo.members.items() if t == 1]), 4)
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST(6), 1)

    def test_pending_rejected_at_approval_time_if_team_changed(self):
        self.team_up([1, 2])                                          # [기획자, 디자이너] 2명
        services.apply_to_team(self.repo, ST(3), 1)                   # 분석가 (3명이 되어도 가능)
        services.apply_to_team(self.repo, ST(4), 1)                   # 발표자 (이 시점엔 3명이라 가능)
        a3 = self.repo.list_applications(student_no="3")[0]["id"]
        a4 = self.repo.list_applications(student_no="4")[0]["id"]
        services.cast_vote(self.repo, ST(1), a3, True)
        services.cast_vote(self.repo, ST(2), a3, True)                # 분석가 승인 -> 3명
        app4 = self.repo.get_application(a4)
        self.assertEqual(app4["status"], "rejected")                  # 승인 직전 재검사: 웹 담당 불가 -> 자동 거절
        self.assertNotIn("4", self.repo.members)
        self.assertTrue(app4["reason"])


class PermissionTest(unittest.TestCase):
    def test_roles_are_separated_in_services(self):
        repo = make_repo(roster(), 4)
        student = ST("20001")
        for call in (lambda: services.initialize(repo, student, [], 1),
                     lambda: services.close_recruitment(repo, student),
                     lambda: services.reopen_recruitment(repo, student),
                     lambda: services.generate_proposal(repo, student, None, []),
                     lambda: services.confirm_proposal(repo, student, 1),
                     lambda: services.close_recruitment(repo, None)):
            with self.assertRaises(services.ServiceError):
                call()
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(repo, ADMIN, 1)                    # 관리자는 학생 기능 사용 불가
        with self.assertRaises(services.ServiceError):
            services.cast_vote(repo, ADMIN, 1, True)
        self.assertEqual(services.get_phase(repo), services.RECRUITING)

    def test_student_cannot_cancel_or_vote_for_someone_else(self):
        repo = make_repo(roster(), 4)
        services.apply_to_team(repo, ST("20001"), 1)
        services.apply_to_team(repo, ST("20004"), 1)
        app = repo.list_applications(status="pending")[0]["id"]
        with self.assertRaises(services.ServiceError):
            services.cancel_application(repo, ST("20007"), app)       # 남의 지원 취소 불가
        with self.assertRaises(services.ServiceError):
            services.cast_vote(repo, ST("20007"), app, True)          # 다른 팀 학생 투표 불가


class AiAndFallbackTest(unittest.TestCase):
    def setUp(self):
        self.teams = {1: [], 2: []}
        from core.rules import Student
        self.free = [Student("1", "a", "기획자", ()), Student("2", "b", "웹 프로그래머", ()),
                     Student("3", "c", "기획자", ()), Student("4", "d", "웹 프로그래머", ())]
        self.good = json.dumps({"assignments": [{"student_no": "1", "team_id": 1}, {"student_no": "2", "team_id": 1},
                                                {"student_no": "3", "team_id": 2}, {"student_no": "4", "team_id": 2}]})

    def test_timeout_constant_and_http_call(self):
        self.assertEqual(ai_assigner.AI_TIMEOUT_SECONDS, 120)
        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["timeout"] = timeout
            captured["auth"] = headers["Authorization"]
            resp = mock.Mock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"choices": [{"message": {"content": "{}"}}]}
            return resp

        with mock.patch.object(ai_assigner.requests, "post", fake_post):
            ai_assigner.call_openrouter("TEST-KEY", "m", [])
        self.assertEqual(captured["timeout"], 120)

    def test_failures_move_to_next_model_in_order_max_three(self):
        calls = []

        def caller(key, model, messages):
            calls.append(model)
            if model == "m1":
                raise requests.Timeout()
            if model == "m2":
                return ""                                      # 빈 응답
            if model == "m3":
                return json.dumps({"assignments": [{"student_no": "1", "team_id": 1}] * 4})   # 잘못된 배정
            return self.good

        a, model, logs = ai_assigner.run_ai_assignment("k", ["m1", "m2", "m3", "m4"], self.teams, self.free, caller=caller)
        self.assertIsNone(a)
        self.assertEqual(calls, ["m1", "m2", "m3"])            # 4번째 모델은 호출하지 않음
        self.assertIn("120초", logs[0])
        self.assertIn("빈 응답", logs[1])
        self.assertIn("폐기", logs[2])

    def test_none_content_is_failure_then_success(self):
        answers = iter([None, self.good])
        a, model, _ = ai_assigner.run_ai_assignment("k", ["m1", "m2"], self.teams, self.free,
                                                    caller=lambda k, m, msgs: next(answers))
        self.assertEqual(model, "m2")
        self.assertEqual(a["3"], 2)

    def test_all_three_fail_then_app_solves_by_itself(self):
        repo = make_repo(roster(), 4)
        services.close_recruitment(repo, ADMIN)
        out = services.generate_proposal(repo, ADMIN, "k", ["a", "b", "c"], ai_caller=lambda *a: "")
        self.assertTrue(out["ok"])
        self.assertEqual(out["proposal"]["source"], "fallback")
        self.assertEqual(sum("빈 응답" in line for line in out["logs"]), 3)
        status = services.get_assign_status(repo)
        self.assertEqual(status["state"], "proposed")

    def test_no_valid_assignment_reports_reason_and_never_confirms(self):
        repo = make_repo([stu(1, "기획자"), stu(2, "기획자"), stu(3, "웹 프로그래머"),
                          stu(4, "웹 프로그래머"), stu(5, "디자이너")], 1)       # 한 팀에 5명 불가 + 같은 주 역할
        services.close_recruitment(repo, ADMIN)
        out = services.generate_proposal(repo, ADMIN, None, [])
        self.assertFalse(out["ok"])
        self.assertEqual(out["message"], "규칙을 지키는 배정이 없음")
        self.assertTrue(any("5명" in r for r in out["reasons"]))
        status = services.get_assign_status(repo)
        self.assertEqual(status["state"], "no_solution")
        self.assertEqual(status["message"], "규칙을 지키는 배정이 없음")
        self.assertTrue(status["reasons"])
        with self.assertRaises(services.ServiceError):
            services.confirm_proposal(repo, ADMIN)                        # 확정할 배정안이 없음
        self.assertEqual(repo.list_members(), [])
        self.assertEqual(services.get_phase(repo), services.CLOSED)

    def test_ai_wrong_answer_is_never_approved_directly(self):
        repo = make_repo(roster(), 4)
        services.close_recruitment(repo, ADMIN)
        wrong = json.dumps({"assignments": [{"student_no": f"20{i:03d}", "team_id": 1} for i in range(1, 17)]})
        out = services.generate_proposal(repo, ADMIN, "k", ["m"], ai_caller=lambda *a: wrong)
        self.assertEqual(out["proposal"]["source"], "fallback")
        services.confirm_proposal(repo, ADMIN)                            # proposal_id 생략 -> 최신 배정안
        snap = services.snapshot(repo)
        self.assertEqual(rules.validate_assignment(snap.members, snap.team_names), [])


class SchemaTest(unittest.TestCase):
    def test_all_tables_start_with_tf_and_match_app_usage(self):
        schema = (ROOT / "schema.sql").read_text(encoding="utf-8")
        created = set(re.findall(r"create table if not exists\s+(\w+)", schema))
        self.assertTrue(created)
        self.assertTrue(all(t.startswith("tf_") for t in created), created)
        used = set(re.findall(r'_t\("(\w+)"\)', (ROOT / "core" / "db.py").read_text(encoding="utf-8")))
        self.assertEqual(used, created)                                   # 앱이 쓰는 테이블 == schema.sql 의 테이블
        for needed in ("primary key", "unique", "check (", "references", "enable row level security"):
            self.assertIn(needed, schema)


if __name__ == "__main__":
    unittest.main()
