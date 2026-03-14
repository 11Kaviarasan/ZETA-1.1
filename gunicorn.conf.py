# gunicorn.conf.py — Production server config for Zeta AI
# Run with: gunicorn -c gunicorn.conf.py app:app

import os

# ── Workers ───────────────────────────────────────────────────────────────────
workers     = 4          # 2x CPU cores + 1 is the rule of thumb
worker_class = "sync"
threads     = 2
timeout     = 120        # AI calls can take a moment

# ── Binding ───────────────────────────────────────────────────────────────────
bind        = "0.0.0.0:" + os.getenv("FLASK_PORT", "5000")

# ── Logging ───────────────────────────────────────────────────────────────────
loglevel    = "info"
accesslog   = "-"        # stdout
errorlog    = "-"        # stdout

# ── Keep-alive ────────────────────────────────────────────────────────────────
keepalive   = 5
