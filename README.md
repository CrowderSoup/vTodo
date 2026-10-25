# vtodo

A personal kanban-style task manager built with Django. Log in with Google, then manage tasks on a customizable board.

## Features

- **Kanban board** — columns that filter tasks by status, tags, or due date (overdue / today / this week)
- **Custom task statuses** — define your own ordered statuses with optional colors
- **Task details** — title, notes, tags, due date, completion tracking
- **Google sign-in** — OAuth login via django-allauth (more providers easy to add)
- **HTMX-powered UI** — fast partial-page updates without a full JS framework
- **Docker-ready** — single Dockerfile, configurable via environment variables

## Requirements

- Python 3.12+

The board runs on the SQLite file Django creates locally. PostgreSQL, Redis, and a Celery worker are the deploy shape. Redis backs invite rate limiting once `CELERY_BROKER_URL` is set, and the worker runs Google Calendar sync every 10 minutes. A local checkout can leave both unset.

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
# edit .env — set SECRET_KEY. DATABASE_URL and CELERY_BROKER_URL are optional locally.

# 5. Run migrations
uv run manage.py migrate

# 6. Start the development server
uv run manage.py runserver
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
| `DATABASE_URL` | Database URL. Unset uses SQLite at `db.sqlite3` | SQLite |
| `CELERY_BROKER_URL` | Redis URL. Unset keeps the cache in memory and skips Redis. Set it for Google Calendar sync | |
| `ALLOWED_HOSTS` | Comma-separated allowed hostnames | `localhost,127.0.0.1` |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated trusted origins | `http://localhost:8000` |
| `GOOGLE_CLIENT_ID` | Web OAuth client ID from Google Cloud Console. The Android app uses this as the ID-token audience. | |
| `GOOGLE_CLIENT_SECRET` | OAuth client secret from Google Cloud Console | |
| `EMAIL_BACKEND` | Django email backend | `console` (prints to stdout) |
| `EMAIL_HOST` | SMTP host | |
| `EMAIL_PORT` | SMTP port | `587` |
| `EMAIL_HOST_USER` | SMTP username | |
| `EMAIL_HOST_PASSWORD` | SMTP password | |
| `EMAIL_USE_TLS` | Enable STARTTLS | `True` |
| `DEFAULT_FROM_EMAIL` | From address for outgoing mail | `vtodo <noreply@example.com>` |

## Authentication

Click "Sign in with Google" on the login page. Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` from a Google Cloud Console OAuth 2.0 Client (Web application type), with the authorized redirect URI set to `<your-domain>/accounts/google/login/callback/`. A new account is created automatically on first login, matched by verified email to any existing account with the same address.

The Android app uses that same web client. It asks Google for an ID token aimed at `GOOGLE_CLIENT_ID`, then `POST /api/v1/auth/google/` checks the token and returns a new API token for that phone. Each phone gets its own token, listed under Settings → API → Signed-in devices, where a lost phone can be signed out. Signing out in the app revokes its token through `POST /api/v1/auth/sign-out/`. The Settings → API token is separate and still works when pasted into the app. `GET /api/v1/auth/google/` returns the client id the app should request. In the same Google Cloud project, add an Android OAuth client for package `com.crowdersoup.vtodo` and the SHA-1 of the signing key (see the Android section below). No new environment variable.

## Running tests

```bash
uv run pytest
```

Browser tests in `tests/browser/` drive headless Chromium through Playwright and run offline. They skip if Chromium isn't installed; set `VTODO_REQUIRE_BROWSER=1` to make that a failure instead.

```bash
uv run playwright install chromium   # once
uv run pytest -m browser             # only the browser tests
uv run pytest -m "not browser"       # everything else
```

## Android

`android/` is a Kotlin app for a home-screen widget. The website stays the source of truth. Sign in with Google, or paste the API token from Settings → API token. Either way the app stores its API token in the Android Keystore and syncs tasks into a local database. If the server rejects the token (it was revoked or regenerated), the app signs itself out and clears that database. The Today screen and the Today widget list open tasks that are overdue or due today. Open lists every task that is not done. Each row shows the status, tags, and, when one is set, how often the task repeats. Open a task to read its notes, change its status, or edit the title, notes, due date, due time, repeat, and tags. Remove deletes the task on the website. Notes use the same Markdown as the website, including lists, links, and checkboxes. Checking one off, or moving it to a completed status, calls `POST /api/v1/tasks/{id}/move/` so recurrence still runs on the server.

The launcher icon is `static/logo.png`. Colors come from the variables in `static/app.css`. The Android build copies both, so the app does not keep a second copy. The widget list scrolls on Android 12 and newer.

A debug build needs a JDK, the Android SDK, and a device or emulator:

```bash
cd android
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
```

Open the app once, enter the server URL, and sign in with Google. Pasting an API token still works. Then long-press the home screen and add the vtodo Today widget. The widget refreshes when you open the app, when you check a task off, and about every 30 minutes. `http://` server URLs only work for a machine on your local network (a private or Tailscale address, `localhost`, a name without a dot, or a `.local`, `.lan`, `.home.arpa`, or `.internal` name), because the API token goes in every request. A server on the internet needs `https://`. A self-signed HTTPS certificate is not.

Google sign-in needs an Android OAuth client next to the web client, with package name `com.crowdersoup.vtodo` and the SHA-1 of the key that signed the build. The server you type in has to be running this version, because the phone asks it for the Google client id and then trades the ID token for an API token.

`android/app/debug.keystore` (alias `androiddebugkey`, password `android`) is committed so local debug builds are reproducible. Its password is public, so anyone can sign an APK with it. Do not hand out debug builds, and do not register its SHA-1 on the production Android OAuth client. A debug build can still sign in to production by pasting an API token, or with Google against a development server whose own Google Cloud project has that SHA-1 registered.

Release builds use a key that is never committed. Create one once and keep a backup, because an installed app only accepts updates signed with the same key:

```bash
keytool -genkeypair -v -keystore vtodo-release.jks -alias vtodo \
  -keyalg RSA -keysize 4096 -validity 10000
keytool -list -v -keystore vtodo-release.jks -alias vtodo   # prints the SHA-1
```

Register that SHA-1 on the Android OAuth client. To build a release locally, put the key in `~/.gradle/gradle.properties`:

```properties
VTODO_RELEASE_KEYSTORE=/path/to/vtodo-release.jks
VTODO_RELEASE_KEYSTORE_PASSWORD=...
VTODO_RELEASE_KEY_ALIAS=vtodo
VTODO_RELEASE_KEY_PASSWORD=...
```

Pushing a change under `android/` runs the Android workflow. It always runs the unit tests and a debug build. With the repository secrets `VTODO_RELEASE_KEYSTORE_BASE64` (the output of `base64 -w0 vtodo-release.jks`), `VTODO_RELEASE_KEYSTORE_PASSWORD`, `VTODO_RELEASE_KEY_ALIAS`, and `VTODO_RELEASE_KEY_PASSWORD` set, it also builds a signed `vtodo.apk` and attaches it to the run:

```bash
adb install -r vtodo.apk
```

A phone that has the old debug-signed build has to uninstall it first, because the signature changed. The phone only holds a copy of the website's data, so sign in again afterwards.

## License

MIT — see [LICENSE](LICENSE).
