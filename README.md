# vtodo

A personal kanban-style task manager built with Django. Log in with your own website via [IndieAuth](https://indieauth.net/) or with a passwordless email OTP, then manage tasks on a customizable board. Optionally post daily summaries to your [Micropub](https://micropub.spec.indieweb.org/) endpoint.

## Features

- **Kanban board** — columns that filter tasks by status, tags, or due date (overdue / today / this week)
- **Custom task statuses** — define your own ordered statuses with optional colors
- **Task details** — title, notes, tags, due date, completion tracking
- **IndieAuth login** — sign in with your website URL using PKCE
- **Email OTP login** — passwordless magic-link / one-time-code via email
- **Micropub integration** — store your Micropub endpoint and token; send daily summaries as `h-entry` posts
- **HTMX-powered UI** — fast partial-page updates without a full JS framework
- **Docker-ready** — single Dockerfile, configurable via environment variables

## Requirements

- Python 3.12+
- PostgreSQL
- Redis (Celery broker for background tasks)

## Local development

```bash
# 1. Clone and enter the repo
git clone https://github.com/CrowderSoup/vtodo.git
cd vtodo

# 2. Install uv (if not already installed)
pip install uv

# 3. Create a virtual environment and install dependencies
uv sync

# 4. Copy and edit the environment file
cp .env.example .env
# edit .env — set DATABASE_URL, CELERY_BROKER_URL, etc.

# 5. Run migrations
uv run manage.py migrate

# 6. Start the development server
uv run manage.py runserver

# 7. (Optional) Start a Celery worker for background tasks
uv run celery -A config worker -l info

# 8. (Optional) Start Celery beat for scheduled tasks (daily summaries)
uv run celery -A config beat -l info
```

## Running with Docker

```bash
docker build -t vtodo .
docker run --env-file .env -p 8000:8000 vtodo
```

The container runs `migrate` automatically on startup before serving with Gunicorn.

## Configuration

All configuration is through environment variables. Copy `.env.example` to `.env` as a starting point.

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Django secret key | *(required)* |
| `DEBUG` | Enable debug mode | `True` |
| `DATABASE_URL` | PostgreSQL connection URL | `postgres://vtodo:vtodo@localhost:5432/vtodo` |
| `CELERY_BROKER_URL` | Redis URL for Celery | `redis://localhost:6379/0` |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `http://localhost:8000` |
| `INDIEAUTH_CLIENT_ID` | Client ID sent to IndieAuth providers | `http://localhost:8000/` |
| `EMAIL_BACKEND` | Django email backend | `console` (prints to stdout) |
| `EMAIL_HOST` | SMTP host | |
| `EMAIL_PORT` | SMTP port | `587` |
| `EMAIL_HOST_USER` | SMTP username | |
| `EMAIL_HOST_PASSWORD` | SMTP password | |
| `EMAIL_USE_TLS` | Enable STARTTLS | `True` |
| `DEFAULT_FROM_EMAIL` | From address for outgoing mail | `vtodo <noreply@example.com>` |

## Authentication

### IndieAuth

Enter your website URL on the login page. Your site must advertise an `authorization_endpoint` and `token_endpoint` (via `<link>` tags or HTTP headers). vtodo uses PKCE for security. On first login a new account is created automatically.

### Email OTP

Enter your email address on the login page. A one-time code is sent to that address. Submit the code to complete login.

## Running tests

```bash
uv run pytest
```

## License

MIT — see [LICENSE](LICENSE).
