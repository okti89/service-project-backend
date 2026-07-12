# Coolify production deployment

## Build configuration

Create a new Dockerfile application in Coolify.

- Base directory: `/backend`
- Dockerfile: `Dockerfile`
- Port: `8000`
- Health check path: `/health/`
- Persistent storage destination: `/app/media`

Coolify injects environment variables at runtime. Copy the names from
`.env.production.example` into the Coolify environment variable panel; do not
commit the real `.env` file.

## Database

Create a PostgreSQL service in Coolify and provide its connection string as
`DATABASE_URL`. SQLite is retained only for local development. A production
container must use PostgreSQL so data survives deployments and can be backed up.

## Local media

Set `R2_ENABLED=False` and add the persistent storage mount at `/app/media`.
With `SERVE_MEDIA_WITH_DJANGO=True`, uploaded files are available at
`/media/` through this application. For a high-traffic installation, put a
reverse proxy or object storage in front of media delivery later.

## First deploy checklist

1. Set a unique random `SECRET_KEY`.
2. Set the public API hostname in `ALLOWED_HOSTS`.
3. Set the dashboard origin in `CORS_ALLOWED_ORIGINS`.
4. Set `CSRF_TRUSTED_ORIGINS` for all HTTPS browser origins.
5. Configure the `/app/media` persistent storage before deploying.
6. Deploy. The entrypoint runs migrations and `collectstatic` before Gunicorn starts.

The Dockerfile build pack uses the Dockerfile directly; Coolify documents the
backend base-directory and port configuration for this deployment type.
