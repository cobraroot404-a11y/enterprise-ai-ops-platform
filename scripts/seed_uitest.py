"""Seed the DEVELOPMENT-ONLY UI test fixture tenant `apex-uitest`.

This tenant exists solely for manual and browser-driven UI testing. It contains only synthetic data
(the same fictional Apex sample files), is named as a test fixture, and is isolated from the primary
`apex-industrial` demo and from all benchmarks (benchmark tooling targets `apex-industrial` explicitly
and refuses `*-uitest` tenants). It is never run by `dev.py seed`, Docker Compose, or CI, and it
refuses to run when EAOP_ENV=production.

Idempotent and deterministic: the same slug, names, users, connectors and documents every time.
Set UITEST_PASSWORD (no default) when running: python scripts/seed_uitest.py
"""
import os
import sys

from seed_apex import refuse_in_production, seed_tenant

SLUG = "apex-uitest"
NAME = "[TEST FIXTURE] Apex UI test tenant (synthetic, development only)"
DOMAIN = "uitest.example.test"


def main() -> None:
    refuse_in_production()
    password = os.environ.get("UITEST_PASSWORD")
    if not password or len(password) < 10:
        sys.exit("Set UITEST_PASSWORD (at least 10 characters) for the UI test fixture users.")
    seed_tenant(SLUG, NAME, DOMAIN, password)


if __name__ == "__main__":
    main()
