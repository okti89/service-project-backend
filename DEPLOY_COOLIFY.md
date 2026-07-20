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

## Membership renewal reminder

Create a daily Coolify scheduled task with the cron expression `0 9 * * *` and the command:

`python manage.py notify_membership_renewals --days 30`

It sends the platform administrator one in-app notification and one email listing the tenants whose current membership period ends within 30 days.
## Daily service summary

Create an application scheduled task in Coolify with the cron expression
`0 8 * * *` and the command:

`python manage.py send_daily_service_summaries`

The command sends one summary per active manager and technician for the current
day. It is idempotent, so retrying the same day does not create duplicate
notifications.

## Shift start reminder

Create another Coolify scheduled task with this cron expression:

`*/15 8-18 * * *`

Command:

`python manage.py send_shift_start_reminders --grace-minutes 10`

It checks each tenant's configured working hours and sends one reminder only after
the start time has passed. Technicians on leave, sick leave, holidays, absences,
or with an open shift are skipped.

## Operational alerts

Create a Coolify scheduled task for unassigned, overdue, and unpaid service
alerts:

`*/30 7-20 * * *`

Command:

`python manage.py send_operational_alerts`

Each recipient receives at most one alert of each type per service per day.

## Shift end reminder

Create a Coolify scheduled task for open shifts after work hours:

`*/15 17-23 * * *`

Command:

`python manage.py send_shift_end_reminders --grace-minutes 15`

Each technician receives one reminder per day only when an open shift remains
after their configured workday ends.

## Notification retention

Create a Coolify scheduled task to remove notifications older than 90 days:

`30 3 * * *`

Command:

`python manage.py cleanup_old_notifications --days 90`

Run the command with `--dry-run` first if you want to review the number of
notifications that will be deleted.
## Subscription expiry reminders

```text
Cron: 0 9 * * *
Command: python manage.py send_subscription_expiry_reminders
```