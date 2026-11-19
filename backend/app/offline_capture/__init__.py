"""OFF-04.4: isolated, idempotent receiver and reconciliation of OFFLINE captures (SYNTHETIC / CI only).

NOT registered in the operational application (`app.main`). It is built on demand by
`create_offline_capture_router(...)`, disabled by default, and its persistence DDL is a PROPOSAL that is not part of the
numbered migrations (see backend/offline_capture_migration/). Technical acceptance is never industrial approval.
"""
