"""Repo-root pytest configuration: one shared set of session fixtures for every test tree
(backend/tests and tests/), so the test database and mock servers are created exactly once."""
pytest_plugins = ["support"]
