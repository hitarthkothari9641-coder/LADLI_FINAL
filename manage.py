"""Owner-only operations. Run with production credentials from a trusted shell."""
import argparse
import getpass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("migrate", "reset-admin", "cleanup"))
    parser.add_argument("--username", default="admin")
    parser.add_argument("--visitor-days", type=int, default=365)
    args = parser.parse_args()
    # Loads local environment without connecting at import time.
    import app
    import db
    if args.command == "migrate":
        if not app.ensure_db_ready():
            raise SystemExit("Migration failed; inspect server logs.")
        print("Schema migrations applied.")
    elif args.command == "reset-admin":
        password = getpass.getpass("New password (12–256 characters): ")
        if not app._password_is_strong(password):
            raise SystemExit("Password must be 12–256 characters.")
        if password != getpass.getpass("Confirm password: "):
            raise SystemExit("Passwords do not match.")
        # Password, history, tokens and forced-change flag commit atomically.
        with db.get_db() as conn:
            db._set_password_in_transaction(conn, args.username, password)
            conn.execute("UPDATE admin_users SET must_change_password = 1 WHERE username = %s", (args.username,))
        print("Password reset. Existing sessions are invalid; change the password at next login.")
    else:
        if args.visitor_days < 1:
            raise SystemExit("Retention must be at least one day.")
        with db.get_db() as conn:
            conn.execute("DELETE FROM password_reset_tokens WHERE used = 1 OR expires_at::timestamptz < CURRENT_TIMESTAMP")
            conn.execute("DELETE FROM recovery_attempts WHERE attempted_at::timestamptz < CURRENT_TIMESTAMP - INTERVAL '30 days'")
            conn.execute("DELETE FROM login_attempts WHERE attempted_at::timestamptz < CURRENT_TIMESTAMP - INTERVAL '30 days'")
            conn.execute("DELETE FROM unique_visitors WHERE last_seen::timestamptz < CURRENT_TIMESTAMP - (%s * INTERVAL '1 day')", (args.visitor_days,))
        print("Expired security records and inactive visitor identifiers removed.")


if __name__ == "__main__":
    main()
