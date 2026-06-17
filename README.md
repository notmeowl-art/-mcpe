# FireMC Shop — Flask (optimized)

## Fixes vs original
- DB now initialises at import (works under gunicorn, no more 404s on first run)
- Proper 404 / 403 / 500 error pages (no more raw "Not Found")
- Favicon route (kills favicon 404 spam)
- SQLite WAL mode + indexes -> faster, no lock-ups
- 7-day static cache headers + lazy-loaded images -> snappier UI
- Removed duplicate hidden field in admin item form
- `threaded=True` dev server, 30-day persistent login session
- `/healthz` endpoint for uptime monitors

## Run (dev)
```bash
pip install -r requirements.txt
python app.py
```
Open http://localhost:5000 — first signup becomes admin.

## Run (production)
```bash
pip install -r requirements.txt
export SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')"
gunicorn -w 2 -b 0.0.0.0:8000 'app:app'
```
