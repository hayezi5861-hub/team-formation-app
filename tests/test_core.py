"""실행: python -m unittest discover -s tests -v   (프로젝트 폴더에서)"""
import itertools
import json
import random
import unittest

from core import ai_assigner, csv_loader, rules, security, services, solver
from core.rules import Student
from tests.fake_repo import FakeRepo

ADMIN = {"role": "admin", "student_no": "admin", "name": "관리자"}


def ST(no):
    return {"role": "student", "student_no": str(no), "name": f"학생{no}"}


def S(no, role, subs=(), name=None):
    return Student(str(no), name or f"학생{no}", role, tuple(subs))


class RulesTest(unittest.TestCase):
    def test_required_roles_need_two_different_people(self):
        solo = S(1, "기획자", ["웹 프로그래머"])           # 한 명이 둘 다 가능해도 혼자면 부족
        self.assertFalse(rules.has_required_roles([solo]))
        self.assertTrue(rules.has_required_roles([solo, S(2, "디자이너", ["웹 프로그래머"])]))
        self.assertTrue(rules.has_required_roles([S(1, "기획자"), S(2, "웹프로그래머")]))  # 공백 차이 허용

    def test_duplicate_main_role_and_size(self):
        team = [S(1, "기획자"), S(2, "웹 프로그래머"), S(3, "디자이너"), S(4, "디자이너")]
        self.assertTrue(any("주 역할" in e for e in rules.team_errors(team)))
        self.assertTrue(rules.team_errors([S(1, "기획자")]))   # 1명은 위반
        self.assertIsNotNone(rules.join_blocker([S(1, "기획자")], S(2, "기획자")))


class CsvTest(unittest.TestCase):
    def test_bom_korean_and_leading_zero(self):
        text = "student_no,name,main_role,sub_roles\n0012,홍길동,기획자,\"웹 프로그래머, 디자이너\"\n"
        students, errors = csv_loader.parse_students(text.encode("utf-8-sig"))
        self.assertEqual(errors, [])
        self.assertEqual(students[0]["student_no"], "0012")
        self.assertEqual(students[0]["sub_roles"], ["웹 프로그래머", "디자이너"])
        students2, _ = csv_loader.parse_students(text.encode("utf-8"))   # BOM 없어도 OK
        self.assertEqual(students2[0]["name"], "홍길동")

    def test_errors(self):
        _, e1 = csv_loader.parse_students("a,b\n1,2\n".encode("utf-8"))
        self.assertTrue(e1)
        _, e2 = csv_loader.parse_students("student_no,name,main_role,sub_roles\n1,가,기획자,\n1,나,기획자,\n".encode())
        self.assertTrue(any("중복" in e for e in e2))
        _, e3 = csv_loader.parse_students("student_no,name,main_role,sub_roles\nadmin,가,기획자,\n".encode())
        self.assertTrue(e3)


class SecurityTest(unittest.TestCase):
    def test_hash(self):
        h = security.hash_password("pw1234")
        self.assertNotIn("pw1234", h)
        self.assertTrue(security.verify_password("pw1234", h))
        self.assertFalse(security.verify_password("wrong", h))
        self.assertNotEqual(h, security.hash_password("pw1234"))
        self.assertTrue(security.verify_admin_password("a", "a"))
        self.assertFalse(security.verify_admin_password("a", ""))


def brute_force_feasible(teams, free):
    ids = sorted(teams)
    for combo in itertools.product(ids, repeat=len(free)):
        merged = {t: list(teams[t]) for t in ids}
        for s, t in zip(free, combo):
            merged[t].append(s)
        if not rules.validate_assignment(merged):
            return True
    return False


class SolverTest(unittest.TestCase):
    def test_matches_brute_force_on_random_cases(self):
        rng = random.Random(7)
        roles = ["기획자", "웹 프로그래머", "디자이너", "분석가"]
        for _ in range(250):
            n_teams = rng.randint(1, 3)
            n_free = rng.randint(0, 6)
            students = [S(i, rng.choice(roles), [r for r in roles if rng.random() < 0.25]) for i in range(n_free + 3)]
            teams = {t: [] for t in range(1, n_teams + 1)}
            pool = list(students)
            rng.shuffle(pool)
            free = pool[:n_free]
            for s in pool[n_free:]:           # 나머지는 기존 팀원 (규칙을 어기지 않는 범위에서)
                t = rng.randint(1, n_teams)
                if not rules.join_blocker(teams[t], s):
                    teams[t].append(s)
                else:
                    free.append(s)
            if len(free) > 7:
                continue
            res = solver.solve(teams, free)
            expected = brute_force_feasible(teams, free)
            self.assertEqual(res.status == "found", expected, (teams, free, res))
            if res.status == "found":
                merged = {t: list(m) for t, m in teams.items()}
                for s in free:
                    merged[res.assignment[s.student_no]].append(s)
                self.assertEqual(rules.validate_assignment(merged), [])

    def test_infeasible_reported(self):
        free = [S(1, "기획자"), S(2, "기획자"), S(3, "웹 프로그래머"), S(4, "웹 프로그래머")]
        res = solver.solve({1: []}, free)    # 한 팀에 같은 주 역할 2명씩 -> 불가능
        self.assertEqual(res.status, "infeasible")

    def test_larger_random_cases_finish_quickly(self):
        roles = ["기획자", "웹 프로그래머", "디자이너", "분석가", "발표자"]
        for seed in range(20):
            rng = random.Random(seed)
            free = [S(i, roles[i % 5], [r for r in roles if r != roles[i % 5] and rng.random() < 0.3])
                    for i in range(rng.choice([20, 30, 32, 40]))]
            n_teams = len(free) // 4
            res = solver.solve({t: [] for t in range(1, n_teams + 1)}, free, max_seconds=10)
            self.assertIn(res.status, ("found", "infeasible"), (seed, res))   # 시간 초과 없이 결론이 나야 함
            if res.status == "found":
                merged = {t: [] for t in range(1, n_teams + 1)}
                for s_ in free:
                    merged[res.assignment[s_.student_no]].append(s_)
                self.assertEqual(rules.validate_assignment(merged), [])


class AiValidationTest(unittest.TestCase):
    def setUp(self):
        self.teams = {1: [S(1, "기획자")], 2: [S(2, "웹 프로그래머")]}
        self.free = [S(3, "웹 프로그래머", ["기획자"]), S(4, "기획자"), S(5, "디자이너"), S(6, "디자이너")]

    def good(self):
        return {"assignments": [{"student_no": "3", "team_id": 1}, {"student_no": "4", "team_id": 2},
                                {"student_no": "5", "team_id": 1}, {"student_no": "6", "team_id": 2}]}

    def test_accepts_valid_and_code_fence(self):
        text = "```json\n" + json.dumps(self.good()) + "\n```"
        a, errs = ai_assigner.validate_ai_assignment(text, self.teams, self.free)
        self.assertEqual(errs, [])
        self.assertEqual(a["3"], 1)

    def test_rejects_rule_violation_and_bad_shapes(self):
        bad = self.good()
        bad["assignments"][3]["team_id"] = 1       # 디자이너 2명이 1팀에
        self.assertIsNone(ai_assigner.validate_ai_assignment(json.dumps(bad), self.teams, self.free)[0])
        missing = {"assignments": self.good()["assignments"][:3]}
        self.assertIsNone(ai_assigner.validate_ai_assignment(json.dumps(missing), self.teams, self.free)[0])
        unknown = self.good(); unknown["assignments"][0]["student_no"] = "99"
        self.assertIsNone(ai_assigner.validate_ai_assignment(json.dumps(unknown), self.teams, self.free)[0])
        moved = self.good(); moved["assignments"].append({"student_no": "1", "team_id": 2})   # 기존 팀원 이동 시도
        self.assertIsNone(ai_assigner.validate_ai_assignment(json.dumps(moved), self.teams, self.free)[0])
        self.assertIsNone(ai_assigner.validate_ai_assignment("죄송합니다", self.teams, self.free)[0])

    def test_model_order_and_fallback_to_next(self):
        calls = []

        def caller(key, model, messages):
            calls.append(model)
            if model == "m1":
                raise RuntimeError("boom")
            if model == "m2":
                return "엉터리 답변"
            return json.dumps(self.good())

        a, model, logs = ai_assigner.run_ai_assignment("k", ["m1", "m2", "m3", "m4"], self.teams, self.free, caller=caller)
        self.assertEqual(calls, ["m1", "m2", "m3"])      # 최대 3개, 순서대로
        self.assertEqual(model, "m3")
        self.assertEqual(len(logs), 3)


def roster():
    """연습용과 무관하게 테스트 안에서 만든 명단 (16명, 4팀)"""
    spec = [("기획자", []), ("기획자", ["웹 프로그래머"]), ("기획자", []), ("웹 프로그래머", []),
            ("웹 프로그래머", ["기획자"]), ("웹 프로그래머", []), ("디자이너", []), ("디자이너", []),
            ("디자이너", ["웹 프로그래머"]), ("디자이너", []), ("분석가", []), ("분석가", []),
            ("분석가", ["기획자"]), ("분석가", []), ("발표자", []), ("발표자", [])]
    return [{"student_no": f"20{i:03d}", "name": f"학생{i}", "main_role": r, "sub_roles": s}
            for i, (r, s) in enumerate(spec, start=1)]


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.repo = FakeRepo()
        self.warnings = services.initialize(self.repo, ADMIN, roster(), 4)

    def test_initialize_and_login(self):
        self.assertEqual(self.warnings, [])
        hashed = self.repo.students["20001"]["password_hash"]
        self.assertNotIn("1234", hashed.split("$")[-1])          # 평문이 아니라 해시
        self.assertTrue(hashed.startswith("pbkdf2_sha256$"))
        self.assertNotEqual(hashed, self.repo.students["20002"]["password_hash"])   # 학생마다 salt 가 다름
        u = services.authenticate(self.repo, "admin", "secret!", "20001", "1234")
        self.assertEqual(u["role"], "student")
        self.assertIsNone(services.authenticate(self.repo, "admin", "secret!", "20001", "20001"))   # 학번은 비밀번호가 아님
        self.assertIsNone(services.authenticate(self.repo, "admin", "secret!", "20001", "bad"))
        self.assertEqual(services.authenticate(self.repo, "admin", "secret!", "admin", "secret!")["role"], "admin")
        self.assertIsNone(services.authenticate(self.repo, "admin", "secret!", "admin", "1234"))

    def test_empty_team_approves_immediately_and_unanimous_vote(self):
        r = services.apply_to_team(self.repo, ST("20001"), 1)
        self.assertEqual(r["status"], "approved")
        self.assertEqual(self.repo.members["20001"], 1)
        # 같은 주 역할은 지원 불가 (규칙 10)
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20002"), 1)
        # 이미 소속된 사람은 다른 팀 지원 불가 (규칙 11)
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20001"), 2)
        r2 = services.apply_to_team(self.repo, ST("20004"), 1)
        self.assertEqual(r2["status"], "pending")
        self.assertNotIn("20004", self.repo.members)
        # 팀원이 아닌 사람은 투표 불가
        app_id = self.repo.list_applications(status="pending")[0]["id"]
        with self.assertRaises(services.ServiceError):
            services.cast_vote(self.repo, ST("20007"), app_id, True)
        res = services.cast_vote(self.repo, ST("20001"), app_id, True)
        self.assertEqual(res["status"], "approved")
        self.assertEqual(self.repo.members["20004"], 1)

    def test_single_reject_rejects(self):
        services.apply_to_team(self.repo, ST("20001"), 1)
        services.apply_to_team(self.repo, ST("20004"), 1)
        a = self.repo.list_applications(status="pending")[0]["id"]
        services.cast_vote(self.repo, ST("20001"), a, True)          # 20004 합류
        services.apply_to_team(self.repo, ST("20007"), 1)            # 이제 두 명의 찬성이 필요
        b = self.repo.list_applications(status="pending")[0]["id"]
        self.assertEqual(services.cast_vote(self.repo, ST("20001"), b, True)["status"], "pending")
        with self.assertRaises(services.ServiceError):           # 중복 투표 불가
            services.cast_vote(self.repo, ST("20001"), b, True)
        self.assertEqual(services.cast_vote(self.repo, ST("20004"), b, False)["status"], "rejected")
        self.assertNotIn("20007", self.repo.members)
        self.assertEqual([v["vote"] for v in self.repo.list_votes(b)], ["approve", "reject"])

    def test_pending_rechecked_when_team_changes(self):
        services.apply_to_team(self.repo, ST("20001"), 1)             # 기획자
        services.apply_to_team(self.repo, ST("20004"), 1)             # 웹 프로그래머 지원
        # 같은 주 역할(웹 프로그래머)의 두 번째 지원자: 지원 시점에는 1팀에 웹 프로그래머가 아직 없어 지원 가능
        services.apply_to_team(self.repo, ST("20005"), 1)
        first, second = [a["id"] for a in self.repo.list_applications(status="pending")]
        services.cast_vote(self.repo, ST("20001"), first, True)       # 20004 합류
        self.assertEqual(self.repo.get_application(second)["status"], "rejected")   # 주 역할 중복으로 자동 거절

    def test_close_and_ai_fallback_and_confirm(self):
        services.apply_to_team(self.repo, ST("20001"), 1)             # 1팀: 1명
        services.apply_to_team(self.repo, ST("20004"), 2)             # 2팀: 1명
        services.apply_to_team(self.repo, ST("20007"), 2)             # 2팀: 대기
        services.apply_to_team(self.repo, ST("20010"), 3)
        services.apply_to_team(self.repo, ST("20011"), 3)             # 3팀: 20010 대기 아님? (20010 디자이너, 20011 분석가)
        info = services.close_recruitment(self.repo, ADMIN)
        self.assertGreaterEqual(info["rejected"], 1)
        self.assertEqual(self.repo.list_applications(status="pending"), [])
        # 1명뿐이던 팀의 학생은 팀에서 빠짐
        for no, t in self.repo.members.items():
            self.assertGreaterEqual(sum(1 for x in self.repo.members.values() if x == t), 2)
        with self.assertRaises(services.ServiceError):
            services.apply_to_team(self.repo, ST("20012"), 1)         # 마감 후 지원 불가

        def bad_ai(key, model, messages):
            return "이건 JSON이 아닙니다"

        out = services.generate_proposal(self.repo, ADMIN, "key", ["a", "b", "c"], ai_caller=bad_ai)
        self.assertTrue(out["ok"], out["logs"])
        self.assertEqual(out["proposal"]["source"], "fallback")
        self.assertEqual(services.get_phase(self.repo), services.CLOSED)
        services.confirm_proposal(self.repo, ADMIN, out["proposal"]["id"])
        self.assertEqual(services.get_phase(self.repo), services.FINALIZED)
        snap = services.snapshot(self.repo)
        self.assertEqual(rules.validate_assignment(snap.members, snap.team_names), [])
        self.assertEqual(snap.free, [])

    def test_ai_valid_answer_is_used(self):
        services.close_recruitment(self.repo, ADMIN)
        free = services.snapshot(self.repo).free
        teams = {t: [] for t in range(1, 5)}
        sol = solver.solve(teams, free).assignment          # 정답을 AI 답변인 것처럼 돌려줌
        answer = json.dumps({"assignments": [{"student_no": k, "team_id": v} for k, v in sol.items()]})
        out = services.generate_proposal(self.repo, ADMIN, "key", ["m1"], ai_caller=lambda k, m, msgs: answer)
        self.assertEqual(out["proposal"]["source"], "ai:m1")
        # AI가 규칙 위반 답을 하면 승인되지 않고 폴백으로 간다
        wrong = json.dumps({"assignments": [{"student_no": s.student_no, "team_id": 1} for s in free]})
        out2 = services.generate_proposal(self.repo, ADMIN, "key", ["m1"], ai_caller=lambda k, m, msgs: wrong)
        self.assertEqual(out2["proposal"]["source"], "fallback")

    def test_cannot_confirm_stale_or_wrong_phase(self):
        with self.assertRaises(services.ServiceError):
            services.confirm_proposal(self.repo, ADMIN, 1)
        with self.assertRaises(services.ServiceError):
            services.generate_proposal(self.repo, ADMIN, None, [])      # 모집 중에는 배정 불가

    def test_password_change(self):
        services.change_password(self.repo, ST("20001"), "1234", "newpass")
        self.assertIsNotNone(services.authenticate(self.repo, "admin", "x", "20001", "newpass"))
        with self.assertRaises(services.ServiceError):
            services.change_password(self.repo, ST("20001"), "wrong", "newpass2")


if __name__ == "__main__":
    unittest.main()
