# What the Laravel port taught us about vTodo

Captured 2026-10-21 from the 2026-10-20 clone at `vTodo-laravel`. That directory was a local experiment, never a git repo, and never pushed. It has been deleted. This note is the record.

The clone was a faithful HTMX port of the personal board: one board per person, status lanes plus filter lanes, tasks with notes, tags, due dates, recurrence, and comments, a month calendar, settings, and a small JSON API. PHPUnit reported 19 passed. A browser pass covered password login, creating a card, moving it to Done, the month calendar, Board Setup, and the API token page.

It left out Google Calendar sync, the MCP server, the OAuth authorization server, and site-admin signup modes and invites. Password login existed so the board could be opened without Google credentials. The two apps were never timed against each other.

## Keep Django

A rewrite onto PHP would not make this board faster. The board rules had to be written again by hand: provisioning, moves, recurrence, filters, the calendar. Blade and HTMX came out about the same size as the Django templates. The clone felt lighter because it ran on SQLite and skipped Redis, Celery, calendar sync, the OAuth server, MCP, and site admin. That is a smaller product.

Keep those pieces. They are the reason the Django app has more machinery, and they are in use:

- Google Calendar sync, on a 10-minute Celery beat (`config/settings.py`, `sync-google-calendar-connections`).
- The MCP server and the OAuth authorization server it depends on.
- The generated API schema.
- Site admin, signup modes, and invites.
- django-allauth's account match. The clone only matched an existing user by email.

`move_task` already lives in `apps/tasks/selectors.py`. `apps/boards/views.py` is still about 900 lines because it owns the board context, calendar-versus-board detection, and the partials. Splitting that file makes the next edit easier. It does not make a click faster.

## Where a click spends its time

The board request has the same shape the clone copied.

`_build_board_context` in `apps/boards/views.py` loads every non-archived task for the user (`board_tasks_qs`) and then filters tags, excluded tags, due date, and search in Python. Lanes are one per status, then one per custom column. A task can appear in its status lane and in every matching custom column. The calendar does the same full load in `apps/boards/views_calendar.py`.

These actions render every lane back into `#task-list-content`:

- A move (`TaskMoveView`), including a drag between lists. `static/app.js` posts that move with `htmx.ajax` targeted at `#task-list-content` and `swap: "innerHTML"`.
- A filter, a saved view, a tag click, hide/show lane, and archive-done.
- A status change from the task panel, which also refreshes the panel (`partials/task_panel_board_response.html` swaps the whole list out of band).
- Creating a task from the panel.

Two paths already avoid that:

- Reordering cards inside one list updates the DOM locally and the server returns 204 (`TaskReorderView`).
- Saving fields from the panel returns the panel plus one card, out of band (`partials/task_panel_update_response.html`).

For a personal board this is one small query plus the HTML for every visible card. The cost to remove, once a click actually feels slow, is rebuilding every column. Pushing tag, due, and search into the query starts to matter once one account has thousands of open cards. `tags` is a `JSONField`. Time one move and one filter on a real account before changing either.

## Return the cards that changed

`templates/partials/task_move_response.html` is an unused one-card response. Nothing renders it, and it does not match the board as it is now. It targets `#tasks-{{ task.status }}`. Lanes are `#col-tasks-{{ lane.dom_id }}`, shaped like `col-tasks-status:123`. Wiring that template up would not move the card.

A partial move response has to account for the board's real rules:

- Custom columns are supplementary. One drop can add or remove the card in several lists, not only the destination status lane.
- Both copies of a card use `id="task-{{ task.pk }}"` (`templates/partials/task_card.html`). `getElementById` in the drag code only sees the first. A partial update needs one address per lane occurrence, or it will update the wrong copy.
- Completing a recurring task can spawn the next card (`move_task` calls `spawn_recurrence`). The response has to include that card, in backlog, and it has to stay quiet when an open sibling already exists.
- The filter bar's done count and the collapsed-lane badges sit outside the card. A move into or out of a done status changes them. A small out-of-band patch covers that. Waiting for the next full render also works if those counts are allowed to lag.
- Filter changes, saved views, and collapse still replace most of the board. Those can keep the full column render.

That is the first code change if a profile says a click is slow. Same-list reorder can stay a 204.

## Make the local loop as small as the clone's

The pleasant part of the clone was operational. SQLite, no Redis, no worker, and a way to sign in without Google credentials.

Django is already half way there, and the docs disagree with the code:

- `config/settings.py` defaults `DATABASE_URL` to `sqlite:///…/db.sqlite3`.
- `README.md` still lists PostgreSQL as a requirement. `.env.example` sets `DATABASE_URL` to local Postgres.
- The cache is `RedisCache`, pointed at `CELERY_BROKER_URL`. The only app use found is invite rate limiting in `apps/siteadmin/views.py`. Tests already use `LocMemCache` in `config/test_settings.py` so the suite does not need Redis.
- Celery's only beat job is the Google Calendar sync every 10 minutes. It is off the board request path. Production still wants the worker, and the Kamal deploy owns the shared Redis accessory. Local board work does not need either.

The local improvement is to make Redis and Celery optional. Default the cache to the in-memory backend when `CELERY_BROKER_URL` is unset. Say in the README that SQLite is enough to run the board, and that Postgres, Redis, and the worker are the deploy shape. A local password or demo user is optional. Google sign-in can stay the real login. The clone added a password only because empty Google credentials would have left it with no way in.

## Leave these alone

- The form posts repeated fields by name (`tags`, `exclude_tags`, `hidden_lanes`). Django's `getlist` keeps every value. The `[]` suffix was a PHP limitation.
- The API token is already showable in settings. The clone had to encrypt a copy because its hash could not be displayed. That is not an improvement to copy.
- Checkbox markdown stays on the small regex in `views.py`. A full task-list markdown extension renders those lines differently. The clone had to avoid that on purpose.
- "Today," overdue, and recurrence already follow the signed-in user's timezone.

## Order to do the work

Shipped on 2026-10-21, on `learnings-from-laravel-port`:

1. Local startup no longer needs Redis. An empty `CELERY_BROKER_URL` uses the in-memory cache. The README and `.env.example` say SQLite is enough for the board, and that Postgres, Redis, and the worker are the deploy shape.
2. A move, a delete, and a panel save redraw only the lanes the card left or joined, including a spawned recurrence and the archive-done count. Each lane occurrence has its own card id (`task-<pk>-<kind>-<lane pk>`). Filters, saved views, collapse, and creating a task still replace the whole list. Tag, due, and search still run in Python.

Still waiting on a real profile before moving those filters into the query. That starts to matter once one account has thousands of open cards.
