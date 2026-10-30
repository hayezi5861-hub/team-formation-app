"""난이도별 명단(쉬움/중간/어려움 CSV)으로 핵심 기능을 끝까지 검증합니다.

tests/data/ 안의 *.csv 를 모두 사용합니다. 지금 들어 있는 파일은 이 프로젝트에서 만든 '연습용 가상 명단'이며,
교수님이 주신 쉬움.csv / 중간.csv / 어려움.csv 를 같은 이름으로 덮어써도 그대로 돌아갑니다.
(결과를 파일 내용에 맞춰 하드코딩하지 않고, '규칙을 지키는가'만 검사합니다.)
"""
import json
import random
import unittest
from math import ceil
from pathlib import Path

from core import csv_loader, rules, services, solver
from tests.fake_repo import FakeRepo
from tests.test_core import ADMIN, ST

DATA = Path(__file__).resolve().parent / "data"
KNOWN_TEAM_COUNTS = {"쉬움": 3, "중간": 6, "어려움": 10}


def load(path):
    students, errors = csv_loader.parse_students(path.read_bytes())
    assert not errors, errors
    return students


def team_count_for(path, students):
    if path.stem in KNOWN_TEAM_COUNTS:
        return KNOWN_TEAM_COUNTS[path.stem]
    free = [services.to_student(s) for s in students]
    for n in range(ceil(len(free) / 4), len(free) // 2 + 1):          # 규칙을 지킬 수 있는 가장 적은 팀 수
        if solver.solve({t: [] for t in range(1, n + 1)}, free, max_seconds=5).status == "found":
            return n
    raise AssertionError("가능한 팀 수를 찾지 못했습니다")


def csv_files():
    files = sorted(DATA.glob("*.csv"))
    assert files, "tests/data 에 CSV 가 없습니다"
    return files


def check_invariants(testcase, repo):
    """어느 순간에 봐도 깨지면 안 되는 규칙들."""
    snap = services.snapshot(repo)
    seen = set()
    for t, members in snap.members.items():
        testcase.assertLessEqual(len(members), rules.MAX_TEAM_SIZE)
        testcase.assertEqual(rules.team_errors(members, check_size=False), [])
        for m in members:
            testcase.assertNotIn(m.student_no, seen)                   # 한 학생은 한 팀에만
            seen.add(m.student_no)
    pending = [a["student_no"] for a in repo.list_applications(status="pending")]
    testcase.assertEqual(len(pending), len(set(pending)))              # 대기 중인 지원은 학생당 최대 1개
    for a in repo.list_applications(status="pending"):
        testcase.assertNotIn(a["student_no"], snap.team_of)


class CsvLevelsTest(unittest.TestCase):
    def test_every_csv_loads_with_bom_and_korean(self):
        for path in csv_files():
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), path.name)     # BOM 이 있어도
            students = load(path)
            self.assertTrue(all(s["name"] and s["main_role"] for s in students))
            self.assertEqual(len({s["student_no"] for s in students}), len(students))

    def test_nobody_applies_then_close_then_ai_fails_then_fallback_confirms(self):
        for path in csv_files():
            with self.subTest(file=path.name):
                students = load(path)
                n_teams = team_count_for(path, students)
                repo = FakeRepo()
                services.initialize(repo, ADMIN, students, n_teams)
                services.close_recruitment(repo, ADMIN)
                out = services.generate_proposal(repo, ADMIN, "k", ["m1", "m2", "m3"],
                                                 ai_caller=lambda *a: "이건 JSON이 아닙니다")
                self.assertTrue(out["ok"], out["logs"])
                self.assertEqual(out["proposal"]["source"], "fallback")
                services.confirm_proposal(repo, ADMIN)
                snap = services.snapshot(repo)
                self.assertEqual(rules.validate_assignment(snap.members, snap.team_names), [])
                self.assertEqual(len(snap.team_of), len(students))             # 모두 정확히 한 팀
                self.assertTrue(all(2 <= len(m) <= 4 for m in snap.members.values()))

    def test_valid_ai_answer_is_accepted_and_invalid_one_is_not(self):
        for path in csv_files():
            with self.subTest(file=path.name):
                students = load(path)
                n_teams = team_count_for(path, students)
                repo = FakeRepo()
                services.initialize(repo, ADMIN, students, n_teams)
                services.close_recruitment(repo, ADMIN)
                free = services.snapshot(repo).free
                good = solver.solve({t: [] for t in range(1, n_teams + 1)}, free).assignment
                answer = json.dumps({"assignments": [{"student_no": k, "team_id": v} for k, v in good.items()]})
                out = services.generate_proposal(repo, ADMIN, "k", ["good-model"], ai_caller=lambda *a: answer)
                self.assertEqual(out["proposal"]["source"], "ai:good-model")
                # 한 학생을 빼먹은 응답, 모두 1팀에 넣은 응답은 승인되지 않고 폴백으로 넘어감
                missing = json.dumps({"assignments": [{"student_no": k, "team_id": v} for k, v in list(good.items())[1:]]})
                allone = json.dumps({"assignments": [{"student_no": k, "team_id": 1} for k in good]})
                for bad in (missing, allone):
                    out = services.generate_proposal(repo, ADMIN, "k", ["bad-model"], ai_caller=lambda *a, b=bad: b)
                    self.assertEqual(out["proposal"]["source"], "fallback")

    def test_random_class_behaviour_never_breaks_invariants(self):
        """학생들이 마구 지원/투표하는 상황을 흉내 내며 규칙이 매 순간 지켜지는지 확인."""
        for path in csv_files():
            for seed in range(3):
                with self.subTest(file=path.name, seed=seed):
                    rng = random.Random(seed)
                    students = load(path)
                    n_teams = team_count_for(path, students)
                    repo = FakeRepo()
                    services.initialize(repo, ADMIN, students, n_teams)
                    nos = [s["student_no"] for s in students]
                    for _ in range(120):
                        no = rng.choice(nos)
                        try:
                            if rng.random() < 0.5:
                                services.apply_to_team(repo, ST(no), rng.randint(1, n_teams))
                            else:
                                items = services.pending_votes_for(repo, no)
                                if items:
                                    app = rng.choice(items)["application"]
                                    services.cast_vote(repo, ST(no), app["id"], rng.random() < 0.85)
                        except services.ServiceError:
                            pass
                        check_invariants(self, repo)
                    services.close_recruitment(repo, ADMIN)
                    self.assertEqual(repo.list_applications(status="pending"), [])
                    snap = services.snapshot(repo)
                    self.assertTrue(all(len(m) != 1 for m in snap.members.values()))   # 1명짜리 팀은 없음
                    out = services.generate_proposal(repo, ADMIN, None, [])
                    if out["ok"]:
                        services.confirm_proposal(repo, ADMIN)
                        snap = services.snapshot(repo)
                        self.assertEqual(rules.validate_assignment(snap.members, snap.team_names), [])
                        self.assertEqual(len(snap.team_of), len(students))
                    else:                                      # 이미 만들어진 팀 때문에 불가능한 경우: 확정하면 안 됨
                        self.assertTrue(out["message"])
                        self.assertTrue(out["reasons"])
                        self.assertEqual(services.get_phase(repo), services.CLOSED)

    def test_hard_roster_solves_within_time(self):
        for path in csv_files():
            students = load(path)
            n = team_count_for(path, students)
            free = [services.to_student(s) for s in students]
            res = solver.solve({t: [] for t in range(1, n + 1)}, free, max_seconds=15)
            self.assertEqual(res.status, "found", path.name)


if __name__ == "__main__":
    unittest.main()
