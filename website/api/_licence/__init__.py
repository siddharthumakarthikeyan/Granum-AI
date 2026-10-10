"""The Granum licence server: accounts, trials, plans and the machines they run on.

It signs licence keys (format in :mod:`.token`, the same as the app's
``granum.licensing.token``) and is the only clock that counts: every date in a key
comes from here.
"""
