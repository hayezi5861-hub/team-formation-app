-- =====================================================================
-- 팀 편성 웹 앱 DB 스키마 (Supabase > SQL Editor 에 통째로 붙여 넣고 Run)
-- 모든 테이블 이름은 tf_ 로 시작합니다. 여러 번 실행해도 안전합니다.
-- =====================================================================

-- 이 앱이 사용하는 테이블은 아래 7개가 전부입니다. (모두 tf_ 로 시작)
--   tf_settings, tf_teams, tf_students, tf_team_members, tf_applications, tf_votes, tf_assignment_proposals

-- 앱 상태 저장 (phase: not_initialized / recruiting / closed / finalized, team_count, assign_status=마지막 AI 배정 결과 JSON)
create table if not exists tf_settings (
    key   text primary key,
    value text not null
);

-- 팀 목록
create table if not exists tf_teams (
    id   integer primary key check (id > 0),
    name text not null
);

-- 학생 명단 (password_hash 에는 비밀번호가 아니라 '해시'가 저장됩니다)
create table if not exists tf_students (
    student_no    text primary key check (length(trim(student_no)) > 0 and lower(student_no) <> 'admin'),
    name          text not null check (length(trim(name)) > 0),
    main_role     text not null check (length(trim(main_role)) > 0),
    sub_roles     text[] not null default '{}',
    password_hash text not null,
    created_at    timestamptz not null default now()
);

-- 팀 소속. student_no 가 기본키이므로 '한 학생은 동시에 한 팀에만' 속하는 규칙을 DB가 직접 보장합니다.
create table if not exists tf_team_members (
    student_no text primary key references tf_students(student_no) on delete cascade,
    team_id    integer not null references tf_teams(id) on delete cascade,
    joined_at  timestamptz not null default now()
);

-- 팀 소속 규칙을 DB가 한 번 더 지킵니다 (앱이 실수하거나 동시에 요청이 와도 규칙이 깨지지 않도록).
--   · 팀 정원 4명 초과 금지
--   · 같은 팀에 같은 주 역할(공백/대소문자 무시) 금지
create or replace function tf_check_member_insert() returns trigger
language plpgsql as $$
declare
    member_count integer;
    same_role_count integer;
begin
    perform pg_advisory_xact_lock(NEW.team_id);   -- 같은 팀에 동시에 들어오는 요청을 한 줄로 세움
    select count(*) into member_count from tf_team_members where team_id = NEW.team_id;
    if member_count >= 4 then
        raise exception '팀 정원(4명)을 초과할 수 없습니다.' using errcode = 'check_violation';
    end if;
    select count(*) into same_role_count
      from tf_team_members m
      join tf_students ms on ms.student_no = m.student_no
      join tf_students ns on ns.student_no = NEW.student_no
     where m.team_id = NEW.team_id
       and regexp_replace(lower(ms.main_role), '\s+', '', 'g') = regexp_replace(lower(ns.main_role), '\s+', '', 'g');
    if same_role_count > 0 then
        raise exception '같은 팀에 주 역할이 같은 학생이 있을 수 없습니다.' using errcode = 'check_violation';
    end if;
    return NEW;
end;
$$;

drop trigger if exists tf_team_members_check on tf_team_members;
create trigger tf_team_members_check
    before insert on tf_team_members
    for each row execute function tf_check_member_insert();

-- 팀 지원 (status: pending 대기 / approved 승인 / rejected 거절 / cancelled 취소)
create table if not exists tf_applications (
    id         bigint generated always as identity primary key,
    student_no text not null references tf_students(student_no) on delete cascade,
    team_id    integer not null references tf_teams(id) on delete cascade,
    status     text not null default 'pending'
               check (status in ('pending', 'approved', 'rejected', 'cancelled')),
    reason     text,
    created_at timestamptz not null default now(),
    decided_at timestamptz
);
-- 한 학생은 동시에 대기 중인 지원을 하나만 가질 수 있음
create unique index if not exists tf_applications_one_pending_per_student
    on tf_applications(student_no) where status = 'pending';

-- 투표 (팀원 한 명이 지원 하나에 한 번만 투표)
create table if not exists tf_votes (
    id             bigint generated always as identity primary key,
    application_id bigint not null references tf_applications(id) on delete cascade,
    voter_no       text not null references tf_students(student_no) on delete cascade,
    vote           text not null check (vote in ('approve', 'reject')),
    created_at     timestamptz not null default now(),
    unique (application_id, voter_no)
);

-- AI/앱이 만든 배정안 (관리자가 확인한 뒤 확정)
create table if not exists tf_assignment_proposals (
    id           bigint generated always as identity primary key,
    source       text not null,                      -- 'ai:모델이름' | 'fallback' | 'none'
    assignment   jsonb not null,                     -- {"학번": 팀번호}
    validation   jsonb not null default '[]'::jsonb, -- 규칙 검사 오류 목록(통과한 안만 저장되므로 보통 비어 있음)
    log          jsonb not null default '[]'::jsonb, -- 어떤 모델이 성공/실패했는지 기록
    status       text not null default 'proposed'
                 check (status in ('proposed', 'confirmed', 'discarded')),
    created_at   timestamptz not null default now(),
    confirmed_at timestamptz
);

-- 처음 상태
insert into tf_settings (key, value) values ('phase', 'not_initialized')
on conflict (key) do nothing;

-- 보안: Row Level Security 를 켜 둡니다. (정책을 만들지 않았으므로 anon/공개 키로는 아무것도 읽을 수 없고,
-- 앱 서버가 쓰는 service_role 키만 접근할 수 있습니다. 비밀번호 해시 보호용)
alter table tf_settings             enable row level security;
alter table tf_teams                enable row level security;
alter table tf_students             enable row level security;
alter table tf_team_members         enable row level security;
alter table tf_applications         enable row level security;
alter table tf_votes                enable row level security;
alter table tf_assignment_proposals enable row level security;
