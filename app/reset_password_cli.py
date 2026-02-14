import argparse
import sys

from sqlalchemy import delete, select

from .auth import hash_password
from .database import SessionLocal
from .models import User, UserSession


def _read_password_from_stdin() -> str:
    # Avoid putting the password in shell history.
    data = sys.stdin.read()
    return (data or "").strip("\r\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset a user's password (offline break-glass tool).")
    parser.add_argument("--username", required=True, help="Username to reset")
    parser.add_argument("--password", help="New password (avoid: shows up in shell history)")
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read new password from stdin (recommended).",
    )
    args = parser.parse_args()

    if bool(args.password) and args.stdin:
        raise SystemExit("Use only one of --password or --stdin")

    new_password = args.password or (_read_password_from_stdin() if args.stdin else "")
    if not new_password:
        raise SystemExit("New password cannot be empty. Use --stdin or --password.")
    if len(new_password) < 12:
        raise SystemExit("New password must be at least 12 characters.")

    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == args.username))
        if user is None:
            raise SystemExit(f"User not found: {args.username}")

        salt, digest = hash_password(new_password)
        user.password_salt = salt
        user.password_hash = digest

        # Force logout everywhere.
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.commit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
