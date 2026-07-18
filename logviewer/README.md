# Ticket Logviewer

A standalone web log viewer for ticket transcripts. Reads from the same MongoDB your bot uses.

## Deploy to Render

1. Go to [render.com](https://render.com) → **New Web Service**
2. Connect your GitHub repo
3. Set **Root Directory** to `logviewer`
4. **Build Command:** `pip install -r requirements.txt`
5. **Start Command:** `python run.py`
6. Add these **Environment Variables** in the Render dashboard:

| Variable | Description |
|---|---|
| `CONNECTION_URI` | Your MongoDB connection string |
| `MONGO_DB_NAME` | Database name (default: `modmail_bot`) |
| `PORT` | Automatically set by Render — leave empty |

7. Copy the deployed URL (e.g. `https://your-logviewer.onrender.com`)
8. In your bot config, set:
   ```
   =config set log_url https://your-logviewer.onrender.com
   =config set log_url_prefix NONE
   ```
   Tickets are then accessible at `https://your-logviewer.onrender.com/ticket-<channel_id>`

## Run Locally

```bash
cd logviewer
pip install -r requirements.txt
cp .env.example .env   # fill in CONNECTION_URI
python run.py
```

Visit `http://localhost:8080/ticket-<channel_id>`
