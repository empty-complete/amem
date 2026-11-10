# amemo-web

The web UI of [amemo](https://github.com/empty-complete/amemo) as static files. The amemo service serves them at
`/ui`; install both with:

```bash
pip install "amemo[web]"
```

The files are built from `web/` in the amemo repository: `cd web && npm ci && npm run build` puts them into
`python/amemo_web/dist`.
