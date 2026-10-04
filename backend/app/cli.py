"""Admin command-line tools. Run from the backend/ folder with the venv active.

    python -m app.cli create-admin --email you@example.com [--role super_admin] [--name "You"]
    python -m app.cli list-admins
    python -m app.cli unblock-ip 203.0.113.7
    python -m app.cli revoke-sessions --email someone@example.com

Against production, run it locally with the production DATABASE_URL, e.g.
    DATABASE_URL='postgresql://…supabase…' JWT_SECRET=anything-32-chars-long… python -m app.cli create-admin --email …

The password is typed interactively (or read from ADMIN_PASSWORD for automation)
and hashed with bcrypt – it never appears on the command line or in source code.
"""

import argparse
import getpass
import os
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.permissions import ADMIN_ROLES, Role
from app.db.session import SessionLocal
from app.models import IpBlock, User
from app.schemas.auth import check_password_rules
from app.services import audit_service, auth_service, ip_block_service, session_service


def _read_password() -> str:
    password = os.environ.get("ADMIN_PASSWORD")
    if password:
        return check_password_rules(password)
    while True:
        first = getpass.getpass("Password (min 8 characters): ")
        second = getpass.getpass("Repeat password: ")
        if first != second:
            print("Passwords don't match, try again.")
            continue
        try:
            return check_password_rules(first)
        except ValueError as error:
            print(error)


def create_admin(args) -> int:
    role = Role(args.role)
    if role not in ADMIN_ROLES:
        print("Role must be read_only_admin, admin or super_admin.")
        return 1
    with SessionLocal() as db:
        user = auth_service.get_user_by_email(db, args.email)
        if user is None:
            password = _read_password()
            user = User(email=args.email.lower(), full_name=args.name, role=role,
                        hashed_password=auth_service.hash_password(password))
            db.add(user)
            db.flush()
            action = "created"
        else:
            print(f"Account {user.email} exists (role: {user.role}).")
            if input(f"Make it {role.value}? [y/N] ").strip().lower() != "y":
                return 1
            if input("Also set a new password? [y/N] ").strip().lower() == "y":
                auth_service.set_password(user, _read_password())
            user.role = role
            user.status = "active"
            session_service.revoke_all(db, user.id, reason="role_changed")
            action = "promoted"
        audit_service.record(db, "ADMIN_CREATED_CLI", target=user, resource_type="user", resource_id=user.id,
                             details={"role": role.value, "action": action}, commit=False)
        db.commit()
        print(f"Done: {user.email} {action} as {role.value}.")
    return 0


def list_admins(_args) -> int:
    with SessionLocal() as db:
        for user in db.scalars(select(User).where(User.role.in_([r.value for r in ADMIN_ROLES])).order_by(User.role)):
            print(f"{user.role:16} {user.status:10} {user.email}")
    return 0


def unblock_ip(args) -> int:
    ip = ip_block_service.normalize_ip(args.ip)
    with SessionLocal() as db:
        blocks = db.scalars(select(IpBlock).where(IpBlock.ip_address == ip, IpBlock.unblocked_at.is_(None))).all()
        for block in blocks:
            block.unblocked_at = datetime.now(timezone.utc)
            block.unblocked_by_email = "cli"
        audit_service.record(db, "IP_UNBLOCKED", resource_type="ip", resource_id=ip, details={"via": "cli"}, commit=False)
        db.commit()
        print(f"Unblocked {ip} ({len(blocks)} block(s)). Running servers pick this up within 30 seconds.")
    return 0


def revoke_sessions(args) -> int:
    with SessionLocal() as db:
        user = auth_service.get_user_by_email(db, args.email)
        if user is None:
            print("No such account.")
            return 1
        count = session_service.revoke_all(db, user.id, reason="cli")
        audit_service.record(db, "USER_FORCE_LOGOUT", target=user, resource_type="user", resource_id=user.id,
                             details={"via": "cli", "sessions_revoked": count}, commit=False)
        db.commit()
        print(f"Revoked {count} session(s) for {user.email}.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Expense Tracker admin tools")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create-admin", help="create an admin account, or promote an existing one")
    p.add_argument("--email", required=True)
    p.add_argument("--name")
    p.add_argument("--role", default="super_admin", choices=["read_only_admin", "admin", "super_admin"])
    p.set_defaults(func=create_admin)

    sub.add_parser("list-admins", help="list admin accounts").set_defaults(func=list_admins)

    p = sub.add_parser("unblock-ip", help="remove an IP from the blocklist (e.g. if you locked yourself out)")
    p.add_argument("ip")
    p.set_defaults(func=unblock_ip)

    p = sub.add_parser("revoke-sessions", help="log an account out everywhere")
    p.add_argument("--email", required=True)
    p.set_defaults(func=revoke_sessions)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
