# Render demo

The demo runs the React frontend and the Dictionary search API in one free
Render Web Service in Singapore. The Docker image contains a read-only SQLite
snapshot with 180 observations. Search by crop, region and year in the query,
for example `ข้าวนาปีภาคใต้ปี 2566` (274,135 tonnes).

## Deploy

1. Push the demo source to a Git repository linked to Render. Keep
   `render.yaml` at the repo root and preserve the `search_service/` paths.
   The demo needs `app/`, `frontend/`, `render_data/`, `Dockerfile.render`
   and `Dockerfile.render.dockerignore` under `search_service/`. The prepared
   source ZIP contains those files and excludes local credentials and caches.
2. In the Render Dashboard, select **New → Blueprint**, choose the repository,
   and verify the service is on the **Free** plan before applying.
3. Open the resulting `onrender.com` URL and try the query above. Render checks
   `/api/health` and `/api/ready` reports the loaded catalog size.

The database is built into each deploy. To publish newer data, replace the
snapshot at `search_service/render_data/catalog.sqlite` with a SQLite backup
of the updated catalog and deploy again. This demo provides Dictionary search;
the Semantic, Hybrid, Compare, and Evaluation views are omitted.

Render can suspend a Free service after 15 minutes without traffic. Allow
about a minute for the first visit after it goes idle.
