# Campus Canvas

A creative college event management website built with Python's `http.server`, SQLite, and plain CSS.

## Run

Use the bundled Python in this Codex workspace:

```powershell
& 'C:\Users\hiral\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' app.py
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

## Deploy on Render

This repo includes `render.yaml`, `runtime.txt`, and `requirements.txt`.

On Render, create a Python Web Service and use:

- Build command: `pip install -r requirements.txt`
- Start command: `python app.py`

Render provides the `PORT` environment variable automatically, and `app.py` already uses it.
