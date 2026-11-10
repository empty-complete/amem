# amem-web

The web UI of [amem](https://github.com/empty-complete/amem) as static files. The amem service serves them at
`/ui`; install both with:

```bash
pip install "amem[web]"
```

The files are built from `web/` in the amem repository: `cd web && npm ci && npm run build` puts them into
`python/amem_web/dist`.
