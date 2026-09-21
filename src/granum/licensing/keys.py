"""Public keys that sign Granum licence keys, by key id.

Only the public halves ship. The private key for ``k1`` is kept by the owner, outside
this repository (``~/.config/granum-admin/signing-k1.pem`` on the machine that issues
keys; see ``tools/granum_licence.py``). To retire a key, add a new one here, issue with
it, and drop the old id once no customer key uses it.
"""

PUBLIC_KEYS: dict[str, str] = {
    "k1": "hItszGZPzRvVN5pivCpoZvP_AIZGyVAmf50JU-0oAME",
}
