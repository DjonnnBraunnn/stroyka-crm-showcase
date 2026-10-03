# StroyKontrol — Construction Company Management System (Showcase)

> 🇩🇪 [Deutsche Version](README.de.md)

**One system for a construction company: sites, tasks with photo reports, rotation crews and the worker camp, heavy equipment and fuel, budget vs. actual, document approval and eight director reports** — built end-to-end by [Johannes Braun](https://github.com/DjonnnBraunnn).

This is a **showcase repository** with selected modules from the private codebase. The system is built for a construction company in Kazakhstan around the director's own structure of the business: construction works, worker camp & warehouse, quarrying, road maintenance and the head office.

---

## 📸 Screenshots

![Director dashboard](assets/director-dashboard.png)

*Director dashboard: the whole company on one screen — sites, overdue tasks, people on rotation, camp occupancy, fuel and budget overruns.*

![Mobile app](assets/mobile-app.png)

*Installable PWA: a foreman takes photos on site — time and GPS position are attached automatically. UI in Russian — built for a client in Kazakhstan. Demo data is fictional.*

![Roles](assets/roles.png)

*Eight roles, each with its own working screen; permissions are enforced on the server, not only hidden in the UI.*

## What the system does

- 🏗️ **Sites** — customer, contract, budget, plan/actual dates, progress, everything else hangs off the site
- ✅ **Tasks** — deadlines, priority, checklist, photo report with time and coordinates; notifications on overdue, deadline change and completion (`backend/app/routers/tasks.py`)
- 👷 **Rotation schedule** — who is on which site and until when; overlapping rotations are rejected
- 🛏️ **Worker camp** — block → room → bed, check-in/out, relocation, occupancy limits and history (`backend/app/routers/camp.py`)
- 🚜 **Equipment & fuel** — shift logs, engine hours, fuel issued vs. norm, overrun flags
- 💰 **Finance** — budget vs. actual per site, expenses, acts, payments, overrun alerts
- 📄 **Documents** — versions, approval sheet; a new version resets approvals, because people signed the previous text (`backend/app/routers/documents.py`)
- 📊 **Eight director reports** — daily / weekly / monthly, Excel export (`backend/app/routers/reports.py`)
- ⏰ **Daily scheduler** — overdue tasks, upcoming check-ins/outs, idempotent (no duplicate notifications) (`backend/app/scheduler.py`)

## Tech stack

| Layer | Tech |
|---|---|
| Backend | Python · FastAPI · SQLAlchemy 2 · JWT |
| Database | PostgreSQL (SQLite for local dev) |
| Frontend | Next.js 14 (app router) · TypeScript · Tailwind · SVG charts without a chart library |
| Mobile | PWA: install to home screen, camera, geolocation, service worker |
| Deployment | Docker Compose behind host nginx, nightly backups |

## What's in this repo

| File | What it shows |
|---|---|
| `backend/app/models.py` | Domain model: directions → sites → tasks, people, camp, equipment, finance, documents; every table is tenant-scoped (`company_id`) |
| `backend/app/auth.py` | JWT auth; the user is re-read from the DB on every request, so a dismissed employee loses access immediately; write permissions per section |
| `backend/app/routers/camp.py` | Bed-level occupancy logic: check-in, relocation, check-out, limits |
| `backend/app/routers/documents.py` | Versioned documents with an approval workflow |
| `backend/app/routers/reports.py` | Aggregations for the eight director reports + Excel export |
| `backend/app/scheduler.py` | Daily notifications without duplicates |
| `backend/tests/test_smoke.py` | End-to-end check of every section, roles and permissions |
| `frontend/lib/roles.ts` | Role/permission matrix shared with the in-app user guide |
| `frontend/lib/api.ts` | Typed API client |
| `.env.example` | 12-factor configuration template |

---

📫 **Contact:** braunjohannes595@gmail.com · Looking for backend/full-stack opportunities (DE/remote).

*Code in this repository is published for portfolio evaluation only. All rights reserved.*
