"""Command line entry point: `goohle-mcp` runs the server, `goohle-mcp auth` signs in."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from goohle_mcp import auth, config


def _serve(_: argparse.Namespace) -> None:
    # Importing the tool modules registers their tools on the shared server.
    from goohle_mcp import prompts  # noqa: F401
    from goohle_mcp.app import mcp
    from goohle_mcp.tools import ga4, search_console, sheets, tag_manager  # noqa: F401

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    mcp.run("stdio")


def _auth(args: argparse.Namespace) -> None:
    path = auth.login(
        Path(args.client_secrets).expanduser(),
        read_only=args.read_only,
        port=args.port,
        open_browser=not args.no_browser,
    )
    access = "read-only" if args.read_only else "read + write"
    print(f"Signed in ({access}). Token saved to {path}")


def _status(_: argparse.Namespace) -> None:
    print(f"Mode:         {config.mode()}  (set GOOHLE_MCP_MODE=read|write|publish)")
    print(f"Token file:   {config.token_file()}  ({'found' if config.token_file().exists() else 'missing'})")
    sa = config.service_account_file()
    print(f"Service acct: {sa if sa else '-'}")
    print(f"Audit log:    {config.audit_log_file()}")
    try:
        creds = auth.get_credentials()
    except auth.AuthError as exc:
        print(f"Credentials:  NOT FOUND - {exc}")
        sys.exit(1)
    scopes = getattr(creds, "scopes", None) or getattr(creds, "granted_scopes", None) or []
    print(f"Credentials:  {type(creds).__module__}.{type(creds).__name__}")
    try:
        email = auth.signed_in_email(creds)
    except Exception as exc:  # Network or refresh problems shouldn't hide the rest.
        email = f"(could not check: {type(exc).__name__}: {exc})"
    print(f"Account:      {email or '(unknown - sign in again with goohle-mcp auth to show it)'}")
    for scope in sorted(scopes):
        print(f"  - {scope}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="goohle-mcp",
        description="MCP server for Google Analytics 4, Search Console and Tag Manager.",
    )
    parser.set_defaults(func=_serve)
    sub = parser.add_subparsers(dest="command")

    login = sub.add_parser("auth", help="Sign in with Google (opens a browser) and store the token.")
    login.add_argument("--client-secrets", required=True, help="OAuth client JSON (type: Desktop app).")
    login.add_argument("--read-only", action="store_true", help="Request read-only scopes only.")
    login.add_argument("--port", type=int, default=0, help="Local callback port (default: random).")
    login.add_argument("--no-browser", action="store_true", help="Print the sign-in URL instead of opening it.")
    login.set_defaults(func=_auth)

    status = sub.add_parser("status", help="Show mode, credential source and granted scopes.")
    status.set_defaults(func=_status)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
