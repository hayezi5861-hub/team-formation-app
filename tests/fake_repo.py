"""테스트 전용 '메모리 DB'. SupabaseRepo 와 같은 함수 이름/동작을 흉내 냅니다.
(진짜 Supabase 없이도 지원/투표/마감 로직을 시험하기 위한 파일)"""
from __future__ import annotations


class FakeRepo:
    def __init__(self):
        self.settings, self.students, self.teams = {}, {}, {}
        self.members, self.apps, self.votes, self.proposals = {}, {}, [], {}
        self._app_id = self._prop_id = 0

    def get_setting(self, key, default=None):
        return self.settings.get(key, default)

    def set_setting(self, key, value):
        self.settings[key] = str(value)

    def reset_all(self):
        self.students, self.teams, self.members = {}, {}, {}
        self.apps, self.votes, self.proposals = {}, [], {}

    def add_students(self, rows):
        for r in rows:
            self.students[r["student_no"]] = dict(r)

    def create_teams(self, n):
        for i in range(1, n + 1):
            self.teams[i] = {"id": i, "name": f"{i}팀"}

    def list_students(self):
        return [{k: v for k, v in s.items() if k != "password_hash"} for s in self.students.values()]

    def get_student(self, no):
        return dict(self.students[no]) if no in self.students else None

    def list_teams(self):
        return list(self.teams.values())

    def list_members(self):
        return [{"student_no": no, "team_id": t} for no, t in self.members.items()]

    def add_member(self, no, team_id):
        if no in self.members:
            raise RuntimeError("duplicate key (student_no)")
        self.members[no] = team_id

    def remove_member(self, no):
        self.members.pop(no, None)

    def create_application(self, student_no, team_id, status="pending", reason=None):
        self._app_id += 1
        app = {"id": self._app_id, "student_no": student_no, "team_id": team_id, "status": status, "reason": reason}
        self.apps[self._app_id] = app
        return dict(app)

    def get_application(self, app_id):
        return dict(self.apps[app_id]) if app_id in self.apps else None

    def list_applications(self, student_no=None, team_id=None, status=None):
        out = []
        for a in self.apps.values():
            if student_no is not None and a["student_no"] != student_no:
                continue
            if team_id is not None and a["team_id"] != team_id:
                continue
            if status is not None and a["status"] != status:
                continue
            out.append(dict(a))
        return out

    def update_application(self, app_id, status, reason=None):
        self.apps[app_id]["status"] = status
        self.apps[app_id]["reason"] = reason

    def add_vote(self, application_id, voter_no, approve):
        if any(v["application_id"] == application_id and v["voter_no"] == voter_no for v in self.votes):
            raise RuntimeError("duplicate vote")
        self.votes.append({"application_id": application_id, "voter_no": voter_no,
                           "vote": "approve" if approve else "reject"})

    def list_votes(self, application_id=None):
        return [dict(v) for v in self.votes if application_id in (None, v["application_id"])]

    def update_password_hash(self, no, hashed):
        self.students[no]["password_hash"] = hashed

    def save_proposal(self, source, assignment, errors, log):
        self._prop_id += 1
        p = {"id": self._prop_id, "source": source, "assignment": dict(assignment),
             "validation": list(errors), "log": list(log), "status": "proposed"}
        self.proposals[self._prop_id] = p
        return dict(p)

    def get_proposal(self, pid):
        return dict(self.proposals[pid]) if pid in self.proposals else None

    def latest_proposal(self):
        open_ = [p for p in self.proposals.values() if p["status"] == "proposed"]
        return dict(open_[-1]) if open_ else None

    def set_proposal_status(self, pid, status):
        self.proposals[pid]["status"] = status

    def discard_open_proposals(self):
        for p in self.proposals.values():
            if p["status"] == "proposed":
                p["status"] = "discarded"
