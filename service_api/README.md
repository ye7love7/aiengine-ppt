# Offline PPT Master FastAPI Service

## Start

```bash
uvicorn service_api.main:app --host 0.0.0.0 --port 8000
```

## Material Directories

- `service_data/materials/docs/`
- `service_data/materials/images/`

## Docs

- Frontend integration: `service_api/FRONTEND_GUIDE.md`
- Demo frontend page: `service_api/frontend.html`
- Dedicated API deps: `api_requirements.txt`

## Examples API

- `GET /api/v1/examples`
- `GET /api/v1/examples/{example_name}`
- `GET /api/v1/examples/{example_name}/download/{artifact_name}`

Examples are exposed as a read-only sample library.
Tasks may also pass `example_reference` to use one example as a style reference during generation.

## Auth

This service does not require frontend Bearer token authentication by default.
If authentication is needed, enforce it in the upstream gateway or forwarding service.

## Optional Trace Header

The upstream service may forward a user identifier header for tracing:

- `X-Request-User-Id`
- `X-User-Id`
- `X-Forwarded-User-Id`

If present, the value is recorded in task state and `run.log`.
