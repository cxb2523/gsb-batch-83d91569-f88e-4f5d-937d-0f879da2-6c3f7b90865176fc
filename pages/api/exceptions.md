---
title: Exceptions
description: psxdata exception hierarchy reference.
---

# Exceptions

All psxdata exceptions inherit from `PSXDataError`.

::: psxdata.exceptions

## Catching exceptions

```python
from psxdata.exceptions import PSXConnectionError, PSXServerError
import psxdata

try:
    df = psxdata.stocks("ENGRO")
except PSXConnectionError:
    print("Network error — PSX unreachable. Check your connection.")
except PSXServerError:
    print("PSX server error — try again later.")
```
