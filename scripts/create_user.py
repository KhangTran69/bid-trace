"""Create a BidTrace reviewer account for the authenticated demo mode.

Run ``alembic upgrade head`` first so the ``users`` table exists. Example:

    python scripts/create_user.py reviewer --display-name "Demo Reviewer"
"""

import argparse
import getpass
import sys

from sqlalchemy import select

from app.auth import hash_password
from app.config import Settings
from app.db import make_engine, make_session_factory
from app.models import User


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("username", help="Sign-in username (1-80 characters)")
    parser.add_argument(
        "--display-name", default=None, help="Name shown in the app header (defaults to username)"
    )
    args = parser.parse_args()

    username = args.username.strip()
    if not username or len(username) > 80:
        print("Username must contain 1 to 80 characters.", file=sys.stderr)
        return 2
    password = getpass.getpass("Password: ")
    if len(password) < 8:
        print("Password must be at least 8 characters.", file=sys.stderr)
        return 2
    if getpass.getpass("Confirm password: ") != password:
        print("Passwords do not match.", file=sys.stderr)
        return 2

    settings = Settings()
    engine = make_engine(settings.database_url)
    factory = make_session_factory(engine)
    try:
        with factory() as session, session.begin():
            if session.scalar(select(User).where(User.username == username)) is not None:
                print(f"Username {username!r} already exists.", file=sys.stderr)
                return 1
            session.add(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    display_name=args.display_name or username,
                )
            )
    finally:
        engine.dispose()
    print(f"Created reviewer account {username!r}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
