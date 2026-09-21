"""Licences: what a copy of Granum may do, checked on this computer.

See :mod:`granum.licensing.token` for the key format and :mod:`granum.licensing.manager`
for how a key is held against machines, clocks and time offline.
"""

from granum.licensing.machine import machine_id
from granum.licensing.manager import LEASE_DAYS, Licensing, get_licensing, set_licensing
from granum.licensing.token import LicenceError

__all__ = ["LEASE_DAYS", "LicenceError", "Licensing", "get_licensing", "machine_id", "set_licensing"]
