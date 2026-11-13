"""Owner-only Telegram front end (Phase 1: menu, help and a read-only source view).

Layers stay separate: `settings` (environment), `auth` (owner policy),
`services` (application boundary over existing GatherRadar components),
`presentation` (Persian text and keyboards), `handlers` (Telegram updates),
`runner` (process lifecycle). Handlers never reach collectors directly.
"""

import logging

# Library convention: the CLI runner configures output; imports alone stay silent.
logging.getLogger('gatherradar.telegram').addHandler(logging.NullHandler())
