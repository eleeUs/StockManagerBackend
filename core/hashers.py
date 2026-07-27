from django.contrib.auth.hashers import Argon2PasswordHasher


class StockArgon2PasswordHasher(Argon2PasswordHasher):
    """
    Argon2id hasher with explicit, version-controlled parameters.

    Why subclass instead of using Django's default Argon2PasswordHasher:
    Django's defaults are reasonable but implicit. Explicit parameters here
    mean the security configuration is readable in code review, tracked in
    git history, and intentionally changed — not accidentally drifted.

    Argon2 variant: Argon2id (Django's default for this hasher).
    Argon2id is the recommended variant per OWASP because it combines
    resistance to both side-channel attacks (Argon2i) and GPU attacks
    (Argon2d).

    Parameter rationale (OWASP minimums in parentheses):
      time_cost   = 2       iterations    (min: 2)
        How many passes the algorithm makes over memory.
        Higher = slower per attempt = harder to brute-force.
        2 is the OWASP minimum; increase to 3-4 if login latency allows.

      memory_cost = 65536   kibibytes = 64 MiB  (min: 19 MiB / 19456 KiB)
        Memory required per hash attempt. The primary defence against
        GPU/ASIC attacks: GPU cores have limited memory per thread, so
        high memory_cost drastically reduces parallelism for an attacker.
        64 MiB is a solid production choice. Increase to 128 MiB if the
        server has headroom and user volume is low.

      parallelism = 1       threads       (min: 1)
        Parallel threads used per hash. Setting this to 1 keeps the cost
        predictable under concurrent login load. An attacker gets no benefit
        from setting it higher because memory_cost already saturates their
        GPU.

      salt_len    = 16      bytes = 128 bits
        Django generates a cryptographically random salt of this length
        per password using os.urandom(). 128 bits provides 2^128 unique
        salts — effectively infinite for any practical attack.
        Never store the salt separately; it is embedded in the hash string.

      hash_len    = 32      bytes = 256 bits output
        Length of the resulting hash. 256 bits is well beyond any
        preimage attack boundary.

    The resulting hash stored in the DB looks like:
      argon2$argon2id$v=19$m=65536,t=2,p=1$<base64 salt>$<base64 hash>

    To upgrade parameters in the future:
      1. Change the values below and deploy.
      2. Django automatically rehashes each user's password on their next
         successful login using the new parameters. No manual migration needed.
         Users who haven't logged in retain the old parameters until they do.
    """

    time_cost    = 2
    memory_cost  = 65536   # 64 MiB in kibibytes
    parallelism  = 1
    salt_len     = 16      # bytes — os.urandom(16) called per password
    hash_len     = 32      # bytes
