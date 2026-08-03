# Phase 1 — Project Foundation

## Overview

Phase 1 establishes the complete structural foundation of the backend: project layout,
environment configuration, Docker setup, the custom user model, JWT authentication,
and the first two resource domains (branches and products).

Every decision made in this phase is load-bearing for all subsequent phases.
Changing any of it after the first migration would require a full database reset.

---

## What Was Built

### Project structure

```
stock_project/
├── config/
│   ├── settings/
│   │   ├── base.py          # shared settings for all environments
│   │   ├── development.py   # dev overrides (silk, extensions, DEBUG=True)
│   │   └── production.py    # prod overrides (security headers, DEBUG=False)
│   ├── urls.py
│   └── wsgi.py
├── apps/
│   ├── users/
│   ├── branches/
│   └── products/
├── core/
│   ├── exceptions.py        # domain exceptions + DRF exception handler
│   ├── pagination.py        # StandardPagination + MovementCursorPagination
│   └── permissions.py       # IsAdmin, IsSeller, IsAdminOrSeller, CanAccessBranch
├── requirements/
│   ├── base.txt
│   ├── development.txt
│   └── production.txt
├── Dockerfile
├── docker-compose.yml
├── manage.py
└── .env.example
```

### Custom user model (`apps/users`)

Django's default user model uses `username` as the login field. This system
uses `email` instead. Because changing the user model after the first migration
is destructive, the custom model is the **very first** thing built — before
any `migrate` command is run.

The model extends `AbstractBaseUser` and `PermissionsMixin`:

- `AbstractBaseUser` provides password hashing and `last_login`. Nothing else.
- `PermissionsMixin` adds `is_superuser`, `groups`, and `user_permissions`,
  which are required for the Django admin to work correctly.
- `UserManager` is required when using `AbstractBaseUser` and handles
  `create_user` and `create_superuser` with email normalization.

```python
# AUTH_USER_MODEL must be set before the first migration
AUTH_USER_MODEL = "users.User"
```

Role field uses `TextChoices` with two values: `admin` and `seller`.

A `CheckConstraint` at the database level enforces the role-branch rule:
- Sellers must have a branch assigned.
- Admins must not have a branch assigned.

This constraint runs at the DB level, meaning it cannot be bypassed even
through direct database access or Django admin.

### JWT authentication

`djangorestframework-simplejwt` is used with token blacklisting enabled.
This makes logout actually invalidate tokens rather than just discarding them
on the client side.

Key configuration decisions:
- `ACCESS_TOKEN_LIFETIME = 8 hours` — appropriate for a business-hours system.
- `ROTATE_REFRESH_TOKENS = True` — every refresh issues a new refresh token,
  limiting the damage of a stolen refresh token.
- `BLACKLIST_AFTER_ROTATION = True` — used refresh tokens are blacklisted,
  so replaying a captured refresh token fails.

### Domain exception handler

All service-layer exceptions map to a consistent HTTP error format:

```json
{
  "error": "machine_readable_code",
  "detail": "Human readable message"
}
```

The `error` field is a stable string the frontend can `switch` on.
The `detail` field is for display only and may change between versions.

### Branch model (`apps/branches`)

Branches are never hard-deleted. Deactivation via `is_active=False` is the
correct approach because movement history references branch records and must
remain intact. `on_delete=PROTECT` on all foreign keys to Branch enforces this
at the database level.

### Product model (`apps/products`)

Products have a `unit_type` field (`unit` or `weight`) that the service layer
uses to validate whether fractional quantities are allowed. Categories are a
separate model (not a `CharField`) so they can be renamed without a bulk update
on the Product table.

---

## Key Technical Decisions

| Decision | Choice | Reason |
|---|---|---|
| User login field | `email` | More natural for business users; avoids username management |
| User model base | `AbstractBaseUser` | Clean schema with no unused fields; full control |
| Branch/Product deletion | Soft-delete (`is_active`) | Historical FK references must remain valid |
| FK on_delete | `PROTECT` everywhere | Prevents accidental data loss; forces explicit deactivation |
| Settings split | `base` / `dev` / `prod` | No risk of production credentials in development |

---

## How to Run

```bash
# Copy and fill environment variables
cp .env.example .env

# Start services
docker-compose up --build

# Apply migrations (creates all tables)
docker-compose exec api python manage.py migrate

# Create the first admin user
docker-compose exec api python manage.py createsuperuser

# API is available at http://localhost:8000/api/v1/
# Swagger UI at http://localhost:8000/api/v1/docs/
```

---

## Endpoints Introduced

```
POST   /api/v1/auth/login/
POST   /api/v1/auth/refresh/
POST   /api/v1/auth/logout/
GET    /api/v1/auth/me/

GET    /api/v1/users/
POST   /api/v1/users/
GET    /api/v1/users/{id}/
PATCH  /api/v1/users/{id}/

GET    /api/v1/branches/
POST   /api/v1/branches/
GET    /api/v1/branches/{id}/
PATCH  /api/v1/branches/{id}/

GET    /api/v1/products/
POST   /api/v1/products/
GET    /api/v1/products/{id}/
PATCH  /api/v1/products/{id}/

GET    /api/v1/products/categories/
POST   /api/v1/products/categories/
```
