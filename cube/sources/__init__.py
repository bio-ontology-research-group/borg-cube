"""Read-only adapters over the group's sources of record.

Nothing in this package writes to ~/pa, ~/org, the research KG or GitHub. Each module
returns typed records that carry enough locator information (path, line, heading) for a
bead's provenance header.
"""

from __future__ import annotations
