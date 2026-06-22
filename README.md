# Campus Canvas

A creative college event management website built with Python's `http.server`, SQLite, and plain CSS.

## Run

Use the bundled Python in this Codex workspace:

```powershell
& 'C:\Users\hiral\.cache\dependencies\python\python.exe' app.py
```

Then open:

```text
http://localhost:8000
```

## Demo Accounts

- Admin: `admin@college.edu` / `admin123`
- Organizer: `organizer@college.edu` / `organizer123`
- Student: `student@college.edu` / `student123`

The SQLite database is created automatically in `data/college_events.db` on first run.

You can choose a different database file with:

```powershell
$env:DATABASE_PATH="C:\campus-canvas-data\college_events.db"
& 'C:\Users\hiral\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
```

## Deploy on Render

This repo includes `render.yaml`, `runtime.txt`, and `requirements.txt`.

On Render, create a Python Web Service and use:

- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`

Render provides the `PORT` environment variable automatically, and `app.py` already uses it.

For real saved data on Render, add a persistent disk:

- Mount path: `/var/data`
- Environment variable: `DATABASE_PATH=/var/data/college_events.db`

Without a persistent disk, Render's service filesystem is temporary and SQLite data can disappear after redeploys or restarts. Render documents that only files written under the attached disk mount path are preserved. Persistent disks require a paid Render web service plan, so `render.yaml` uses `starter` instead of `free`.
