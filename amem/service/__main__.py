"""python -m amem.service [--host H] [--port P] [--no-auth] — запуск службы; то же, что `amem serve` (amem/cli)."""
from .server import main

raise SystemExit(main())
