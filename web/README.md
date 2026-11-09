# amem web UI

React 19, HeroUI v3, TanStack Router and Query, Vite. The design system is in [DESIGN.md](DESIGN.md); the product
context is in [PRODUCT.md](PRODUCT.md); the HTTP contract is [`../docs/api/http-v1.openapi.yaml`](../docs/api/).

Node 24+.

```bash
npm ci
```

## Three ways to run it

| Command            | What you get                                                                                                        |
| ------------------ | ------------------------------------------------------------------------------------------------------------------- |
| `npm run dev:mock` | The app on sample data (MSW mocks of the contract), http://127.0.0.1:5173/ui/                                       |
| `npm run dev`      | The app against a running `amem serve`; `/api` is proxied to http://127.0.0.1:8767 (override with `AMEM_URL`)       |
| `npm run build`    | Production build into `python/amem_web/dist`; `pip install "amem[web]"` ships it and the service serves it at `/ui` |

For `npm run dev`, start the service with the dev server's origin allowed, so the page gets the person's session
and may write:

```bash
AMEM_UI_ORIGINS=http://127.0.0.1:5173 python -m amem.service   # `amem serve` once the CLI ships
```

The proxy never rewrites `Origin`: that would let any page write to the base through the dev server.

`npm run build:mock` builds the app with mocks into `dist-mock`; `vite preview` serves it with the same
Content-Security-Policy as the service.

## Checks

```bash
npm run lint
npm run api:check   # src/api/schema.d.ts matches the contract
npm run typecheck
npm test            # every mock response is validated against the contract
npm run build && npm run chunks && npm run size
npm run e2e         # desktop, phone, and "csp": the mock build under the service's CSP
```

## Content Security Policy

The service serves `/ui` with `script-src 'self'`, so:

- there are no inline scripts; `public/boot.js` runs before the modules (theme without a flash, zod without JIT);
- pdf.js 6 does not generate code at run time, so it needs no exception;
- the `csp` e2e project fails on any CSP violation or console error.
