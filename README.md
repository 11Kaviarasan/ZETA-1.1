# Zeta AI — Deployment Guide

## File Structure
```
/zeta-ai/
  app.py              ← Flask backend (main entry point)
  db.py               ← MongoDB layer
  mars_ai.py          ← AI engine adapter
  proper_ai.py        ← AI chain: Gemini → OpenAI → Wikipedia
  index.html          ← Complete frontend SPA
  .env                ← API keys (DO NOT COMMIT)
  requirements.txt    ← Python dependencies
  gunicorn.conf.py    ← Production server config
```

---

## 1. Install Dependencies

```bash
cd /your/project/folder
pip install -r requirements.txt
```

---

## 2. Configure .env

Open `.env` and set your **Razorpay** keys (the others are pre-filled):

```
RAZORPAY_KEY_ID=rzp_live_XXXXXXXXXXXXXXX
RAZORPAY_KEY_SECRET=XXXXXXXXXXXXXXXXXXXXXXXX
RAZORPAY_WEBHOOK_SECRET=XXXXXXXXXXXXXX
```

Also verify your MongoDB URI is correct — it should look like:
```
MONGO_URI=mongodb+srv://user:password@cluster.mongodb.net/zetaai
```

---

## 3. Run (Development)

```bash
python app.py
```
Open: http://localhost:5000

---

## 4. Run (Production on your Oracle server)

```bash
gunicorn -c gunicorn.conf.py app:app
```

To run as a persistent background service with systemd:

```bash
# Create service file
sudo nano /etc/systemd/system/zetaai.service
```

Paste:
```ini
[Unit]
Description=Zeta AI
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/zeta-ai
ExecStart=/usr/local/bin/gunicorn -c gunicorn.conf.py app:app
Restart=always
RestartSec=5
Environment=PATH=/usr/local/bin

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable zetaai
sudo systemctl start zetaai
sudo systemctl status zetaai
```

---

## 5. Nginx Reverse Proxy (recommended)

```nginx
server {
    listen 80;
    server_name zetaai.com www.zetaai.com;

    location / {
        proxy_pass         http://127.0.0.1:5000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }
}
```

---

## 6. Razorpay Webhook

In your Razorpay dashboard, set the webhook URL to:
```
https://www.zetaai.com/api/webhooks/razorpay
```
Select events: `payment.captured`, `subscription.activated`

---

## AI Engine Chain

| Priority | Engine | Condition |
|----------|--------|-----------|
| 1 | Small Talk | Greetings / identity questions |
| 2 | Pinecone Cache | Score >= 0.92 similarity |
| 3 | Gemini 1.5 Pro | Primary (Velauris 1.1) |
| 4 | GPT-4o | If Gemini errors/rate-limits |
| 5 | Wikipedia | Deep factual fallback |
| 6 | Hard fallback | Polite error message |
