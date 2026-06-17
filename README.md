# FireMC Shop — Python / Flask

A Flask + SQLite port of the FireMC coin shop. Fully self-contained: no external services, no API keys.

## Features
- Coin-based shop (ranks, kits, weapons)
- Email + password auth (first sign-up = admin)
- Buy flow with Minecraft username + contact
- Orders dashboard (users see own; admins see all & confirm/cancel)
- Earn coins: wait-timer link tasks
- Leaderboard (top 20)
- Admin panel: manage items, give coins, change roles, manage earn links

## Run

```bash
pip install flask
python app.py
```

Open <http://localhost:5000>.

The first account you register becomes the **admin**. Use a different email
for normal players.

## Files

```
app.py              Flask app + SQLite schema + all routes
templates/          Jinja2 templates
static/style.css    Dark theme styling
static/img/         Item images (rank, kit, sword, bow, armor, hero)
firemc.db           Created automatically on first run
```

## Deploy

Any host that runs Python works (Render, Railway, Fly, a VPS). For
production set `SECRET_KEY` env var and run behind gunicorn:

```bash
pip install gunicorn
gunicorn -w 2 -b 0.0.0.0:8000 'app:app'
```
