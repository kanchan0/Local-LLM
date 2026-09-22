from __future__ import annotations

import argparse
import getpass
import sys

from app.config import Settings
from app.database import UserDatabase
from app.security import hash_password


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a local chat user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--admin", action="store_true", help="create an administrator")
    parser.add_argument("--password", help="avoid this in shell history; prompt is preferred")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not args.password:
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            print("Passwords do not match.", file=sys.stderr)
            return 2
    try:
        password_hash = hash_password(password)
        settings = Settings.from_env()
        settings.ensure_directories()
        database = UserDatabase(settings.database_path)
        database.initialize()
        user_id = database.create_user(args.username, password_hash, "admin" if args.admin else "user")
    except Exception as exc:
        print(f"Could not create user: {exc}", file=sys.stderr)
        return 1
    print(f"Created {args.username} (id={user_id}, role={'admin' if args.admin else 'user'}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
