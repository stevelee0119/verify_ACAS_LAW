#!/usr/bin/env python3
"""관리자 계정을 만든다.

인증을 끄는 스위치가 없으므로, 계정이 없으면 API는 503으로 거부한다.
이 스크립트가 그 상태를 푸는 경로다.

    python scripts/create_admin.py --email admin@example.com

비밀번호는 인자로 받지 않는다. 명령행 인자는 프로세스 목록과 셸 기록에 남는다.
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.auth import ROLES, hash_password  # noqa: E402
from apps.api.db import Organization, User, get_session_factory, init_db  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="관리자 계정 생성")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", default="관리자")
    parser.add_argument("--role", default="ADMIN", choices=list(ROLES))
    parser.add_argument("--org", default="기본 기관", help="기관이 없을 때 새로 만들 이름")
    args = parser.parse_args()

    email = args.email.strip().lower()
    password = getpass.getpass("비밀번호(10자 이상): ")
    if password != getpass.getpass("비밀번호 확인: "):
        print("비밀번호가 일치하지 않는다.", file=sys.stderr)
        return 1
    try:
        password_hash = hash_password(password)
    except ValueError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1

    init_db()
    session = get_session_factory()()
    try:
        if session.query(User).filter(User.email == email).first() is not None:
            print(f"이미 존재하는 이메일이다: {email}", file=sys.stderr)
            return 1
        organization = session.query(Organization).first()
        if organization is None:
            organization = Organization(name=args.org)
            session.add(organization)
            session.flush()
        user = User(
            email=email, display_name=args.name, role=args.role,
            organization_id=organization.id, password_hash=password_hash,
        )
        session.add(user)
        session.commit()
        print(f"생성 완료: {user.email} ({user.role}) / 기관 {organization.name}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
