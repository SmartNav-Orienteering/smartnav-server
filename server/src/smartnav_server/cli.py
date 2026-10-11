"""`smartnav` command-line tool.

    smartnav serve [--host 0.0.0.0] [--port 8000]
    smartnav create-owner --email you@club.org --name "Your Name"
    smartnav reset-password --email you@club.org
    smartnav rescore EVENT_ID
    smartnav plugins
    smartnav demo
"""
from __future__ import annotations

import argparse
import getpass
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="smartnav", description="SmartNav server")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="Run the web server")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    c = sub.add_parser("create-owner", help="Create an owner account")
    c.add_argument("--email", required=True)
    c.add_argument("--name", required=True)
    r = sub.add_parser("reset-password", help="Set a new password for a user")
    r.add_argument("--email", required=True)
    rs = sub.add_parser("rescore", help="Rescore every run of an event")
    rs.add_argument("event_id")
    sub.add_parser("plugins", help="List installed event types")
    sub.add_parser("demo", help="Create a sample series with simulated runs")
    a = p.parse_args(argv)

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("smartnav_server.main:app", host=a.host, port=a.port, proxy_headers=True,
                    forwarded_allow_ips="*")
        return 0

    from sqlalchemy import func, select

    from .auth import audit, hash_password
    from .config import get_settings
    from .db import Event, User, init_engine, new_session

    init_engine(get_settings().db_url)
    db = new_session()

    if a.cmd == "plugins":
        from .plugins import registry

        for k, v in registry().items():
            print(f"{k:12} {v.name}: {v.description}")
        return 0

    if a.cmd == "create-owner":
        email = a.email.strip().lower()
        if db.scalar(select(User).where(func.lower(User.email) == email)):
            print("A user with that email already exists.", file=sys.stderr)
            return 1
        pw = _password()
        u = User(name=a.name, email=email, password_hash=hash_password(pw), role="owner")
        db.add(u)
        db.flush()
        audit(db, u, "create owner (command line)", email)
        db.commit()
        print(f"Owner {email} created.")
        return 0

    if a.cmd == "reset-password":
        u = db.scalar(select(User).where(func.lower(User.email) == a.email.strip().lower()))
        if not u:
            print("No user with that email.", file=sys.stderr)
            return 1
        u.password_hash = hash_password(_password())
        u.active = True
        audit(db, None, "reset password (command line)", u.email)
        db.commit()
        print("Password changed.")
        return 0

    if a.cmd == "demo":
        from .demo import create_demo

        made = create_demo(db)
        print("Created demo events: " + (", ".join(made) or "none (they already exist)"))
        return 0

    if a.cmd == "rescore":
        from .scoring import rescore_event

        ev = db.get(Event, a.event_id)
        if not ev:
            print("No such event.", file=sys.stderr)
            return 1
        n = rescore_event(db, ev)
        db.commit()
        print(f"{n} run(s) rescored.")
        return 0
    return 1


def _password() -> str:
    while True:
        pw = getpass.getpass("New password (at least 10 characters): ")
        if len(pw) < 10:
            print("Too short.")
            continue
        if getpass.getpass("Repeat: ") != pw:
            print("Passwords do not match.")
            continue
        return pw


if __name__ == "__main__":
    raise SystemExit(main())
