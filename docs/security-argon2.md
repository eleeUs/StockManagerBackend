# Security — Password Hashing Upgrade to Argon2id

## Overview

The default Django password hasher (PBKDF2 + SHA-256) is acceptable for
internal systems but is vulnerable to GPU-based brute-force attacks because
SHA-256 is cheap to compute in parallel on graphics hardware.

Since this system is exposed to the internet, the hasher is upgraded to
**Argon2id** — the winner of the 2015 Password Hashing Competition and the
current OWASP recommendation for new systems.

---

## Changes

### New dependency

```
argon2-cffi==23.1.0
```

Added to `requirements/base.txt`. `argon2-cffi` is the Python binding for the
reference Argon2 C implementation.

### Custom hasher (`core/hashers.py`)

Django's built-in `Argon2PasswordHasher` uses reasonable defaults, but they
are implicit — buried in Django's source code and subject to change between
Django versions without a visible diff in this repository.

`StockArgon2PasswordHasher` subclasses it with explicit, documented parameters:

```python
class StockArgon2PasswordHasher(Argon2PasswordHasher):
    time_cost    = 2
    memory_cost  = 65536   # 64 MiB
    parallelism  = 1
    salt_len     = 16      # bytes
    hash_len     = 32      # bytes
```

Any future change to these parameters is a deliberate, reviewable commit —
not a silent Django upgrade.

### Settings (`config/settings/base.py`)

```python
PASSWORD_HASHERS = [
    "core.hashers.StockArgon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
```

---

## Parameter Rationale

### Argon2id variant

Argon2 has three variants: `i`, `d`, and `id`. OWASP recommends `id` for
password hashing because it combines:
- **Argon2i** resistance to side-channel attacks (constant-memory-access pattern).
- **Argon2d** resistance to GPU/ASIC attacks (data-dependent memory access).

Django's `Argon2PasswordHasher` uses `argon2id` by default.

### `time_cost = 2`

Number of passes the algorithm makes over memory. Each additional pass doubles
the time cost for both legitimate login and an attacker's brute-force attempt.
2 is the OWASP minimum and produces sub-100ms login times on typical server
hardware. Increase to 3 if server capacity allows.

### `memory_cost = 65536` (64 MiB)

Memory required per hash attempt. This is the primary defence against GPU
attacks: a GPU with thousands of cores has limited memory per core, so a high
`memory_cost` forces the attacker to use far fewer parallel threads than their
GPU would otherwise support.

OWASP minimum is 19 MiB. 64 MiB provides significantly better protection with
acceptable memory overhead on a typical API server.

### `parallelism = 1`

Number of threads used per hash. Set to 1 to keep the login cost predictable
under concurrent user load. An attacker gains no advantage from this setting
because `memory_cost` already saturates their GPU memory per thread.

### `salt_len = 16` (128 bits)

Django generates a cryptographically random salt of this length via
`os.urandom(16)` for every password. The salt is embedded in the stored hash
string — it never needs to be stored or managed separately. 128 bits provides
`2^128` unique salts, making precomputed rainbow table attacks infeasible.

### `hash_len = 32` (256 bits)

Output length of the hash. 256 bits is well beyond any known preimage attack
boundary and matches the output length of SHA-256.

---

## Hash Format in the Database

```
argon2$argon2id$v=19$m=65536,t=2,p=1$<base64 salt>$<base64 hash>
```

The hash string is self-describing. Django reads the prefix to determine which
hasher and parameters to use for verification — no separate metadata table or
migration is needed.

---

## Automatic Rehashing

Django rehashes a user's password on their next successful login if it was
hashed with a lower-priority algorithm (e.g. PBKDF2 from development). No
manual migration or user action is required. The PBKDF2 fallback in
`PASSWORD_HASHERS` exists precisely for this transition period.

Users who have never logged in since the upgrade retain their old hash until
they do. Their passwords remain valid and are upgraded transparently on login.

---

## Upgrading Parameters in the Future

1. Update the values in `core/hashers.py`.
2. Deploy.
3. Django rehashes each user's password on their next login automatically.

No database migration is needed. The hash string stores all parameters
required for verification.
