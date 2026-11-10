"""python -m amemo.service [--host H] [--port P] [--no-auth] — запуск службы; то же, что `amemo serve` (amemo/cli)."""
from .server import main

raise SystemExit(main())
