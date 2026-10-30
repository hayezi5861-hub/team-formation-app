"""Supabase(데이터베이스) 접근 모듈.

services.py 가 요구하는 '저장소(repo)' 함수들을 Supabase로 구현했습니다.
SQL을 직접 쓰지 않고 supabase-py 의 table("테이블").select/insert/update/delete 를 사용합니다.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st
from supabase import create_client

from core import config


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@st.cache_resource
def get_repo():
    """Supabase 연결은 한 번만 만들어 재사용합니다. (키는 Secrets/환경 변수에서만 읽음)"""
    client = create_client(config.get_secret("SUPABASE_URL"), config.get_secret("SUPABASE_KEY"))
    return SupabaseRepo(client)


class SupabaseRepo:
    def __init__(self, client):
        self.c = client

    def _t(self, name: str):
        return self.c.table(name)

    # ---- 설정
    def get_setting(self, key, default=None):
        res = self._t("tf_settings").select("value").eq("key", key).execute()
        return res.data[0]["value"] if res.data else default

    def set_setting(self, key, value):
        self._t("tf_settings").upsert({"key": key, "value": str(value)}).execute()

    # ---- 초기화 (자식 테이블부터 지움)
    def reset_all(self):
        self._t("tf_assignment_proposals").delete().gt("id", 0).execute()
        self._t("tf_votes").delete().gt("id", 0).execute()
        self._t("tf_applications").delete().gt("id", 0).execute()
        self._t("tf_team_members").delete().neq("student_no", "").execute()
        self._t("tf_teams").delete().gt("id", 0).execute()
        self._t("tf_students").delete().neq("student_no", "").execute()

    # ---- 학생 / 팀
    def add_students(self, rows):
        for i in range(0, len(rows), 200):
            self._t("tf_students").insert(rows[i:i + 200]).execute()

    def create_teams(self, n):
        self._t("tf_teams").insert([{"id": i, "name": f"{i}팀"} for i in range(1, n + 1)]).execute()

    def list_students(self):
        # 비밀번호 해시는 일부러 가져오지 않습니다.
        return self._t("tf_students").select("student_no,name,main_role,sub_roles").order("student_no").execute().data

    def get_student(self, student_no):
        res = self._t("tf_students").select("*").eq("student_no", student_no).execute()
        return res.data[0] if res.data else None

    def update_password_hash(self, student_no, hashed):
        self._t("tf_students").update({"password_hash": hashed}).eq("student_no", student_no).execute()

    def list_teams(self):
        return self._t("tf_teams").select("*").order("id").execute().data

    # ---- 팀 소속
    def list_members(self):
        return self._t("tf_team_members").select("student_no,team_id").execute().data

    def add_member(self, student_no, team_id):
        self._t("tf_team_members").insert({"student_no": student_no, "team_id": team_id}).execute()

    def remove_member(self, student_no):
        self._t("tf_team_members").delete().eq("student_no", student_no).execute()

    # ---- 지원
    def create_application(self, student_no, team_id, status="pending", reason=None):
        row = {"student_no": student_no, "team_id": team_id, "status": status, "reason": reason}
        if status != "pending":
            row["decided_at"] = _now()
        return self._t("tf_applications").insert(row).execute().data[0]

    def get_application(self, application_id):
        res = self._t("tf_applications").select("*").eq("id", application_id).execute()
        return res.data[0] if res.data else None

    def list_applications(self, student_no=None, team_id=None, status=None):
        q = self._t("tf_applications").select("*")
        if student_no is not None:
            q = q.eq("student_no", student_no)
        if team_id is not None:
            q = q.eq("team_id", team_id)
        if status is not None:
            q = q.eq("status", status)
        return q.order("id").execute().data

    def update_application(self, application_id, status, reason=None):
        self._t("tf_applications").update(
            {"status": status, "reason": reason, "decided_at": None if status == "pending" else _now()}
        ).eq("id", application_id).execute()

    # ---- 투표
    def add_vote(self, application_id, voter_no, approve):
        self._t("tf_votes").insert({
            "application_id": application_id, "voter_no": voter_no,
            "vote": "approve" if approve else "reject",
        }).execute()

    def list_votes(self, application_id=None):
        q = self._t("tf_votes").select("*")
        if application_id is not None:
            q = q.eq("application_id", application_id)
        return q.order("id").execute().data

    # ---- 배정안
    def save_proposal(self, source, assignment, errors, log):
        row = {"source": source, "assignment": assignment, "validation": errors, "log": log}
        return self._t("tf_assignment_proposals").insert(row).execute().data[0]

    def get_proposal(self, proposal_id):
        res = self._t("tf_assignment_proposals").select("*").eq("id", proposal_id).execute()
        return res.data[0] if res.data else None

    def latest_proposal(self):
        res = (self._t("tf_assignment_proposals").select("*").eq("status", "proposed")
               .order("id", desc=True).limit(1).execute())
        return res.data[0] if res.data else None

    def set_proposal_status(self, proposal_id, status):
        update = {"status": status}
        if status == "confirmed":
            update["confirmed_at"] = _now()
        self._t("tf_assignment_proposals").update(update).eq("id", proposal_id).execute()

    def discard_open_proposals(self):
        self._t("tf_assignment_proposals").update({"status": "discarded"}).eq("status", "proposed").execute()
