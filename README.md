# Regnova Backend

See `CLAUDE.md` for the full architecture/module/decision reference.

## Local development

```bash
pip install -e ".[dev]"
uvicorn app.main:app --reload
pytest
```

### Postgres and ClamAV via Docker

```bash
docker compose up -d
docker compose logs -f clamav   # watch startup
```

This starts Postgres (port 5432, matching `Settings.database_url`'s
default) and ClamAV (port 3310) for local development. Neither is
required to run `pytest` - tests use an in-memory SQLite database and
a no-op malware scanner by default (see `CLAUDE.md` "Malware
scanning").

**ClamAV's first start is slow, and that's expected.** On first start
(or whenever its data volume is empty), the container downloads the
virus definition database — routinely several minutes, longer on a
slow connection — before it will accept any scan connection at all.
Until that finishes, every scan attempt from the backend gets
connection-refused, which the app reports as `ScannerUnavailable` and
lands the upload's document version in `FAILED`. That is not a bug or
a misconfiguration if it happens right after `docker compose up` — it
means ClamAV is still downloading its database, not that anything is
broken. Check `docker compose logs clamav` (or
`docker inspect --format '{{.State.Health.Status}}' regnova-clamav`)
and wait for `healthy` before uploading anything through the real
backend with `MALWARE_SCANNER_BACKEND=clamav` set.

To actually use ClamAV (rather than the default no-op scanner), set in
`backend/.env`:

```
MALWARE_SCANNER_BACKEND=clamav
```

See `docker/clamav/clamd.conf`'s own header comment for the
`StreamMaxLength` setting that keeps ClamAV's own upload-size ceiling
aligned with `Settings.document_max_size_bytes` (100 MB) — and for a
correction of the commonly-assumed "25 MB default" claim, which this
image's actual compiled default does not match.
