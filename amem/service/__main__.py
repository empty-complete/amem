"""python -m amem.service [--host H] [--port P] [--no-auth] — запуск службы до появления `amem serve` (CLI, часть 4b)."""
from .server import main

raise SystemExit(main())
