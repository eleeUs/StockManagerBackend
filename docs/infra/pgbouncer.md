# PgBouncer — connection pooling

Fase 10, Equipo A. Ver `docs/roadmap-fases-7-10.md` (objetivo original) y
`docs/phase-10-plan.md` (plan completo con las diferencias respecto al plan
inicial).

## Por qué

`gunicorn.conf.py` corre workers `sync` (`2×CPU+1`), cada uno capaz de
sostener una conexión a Postgres mientras atiende un request. Sin pooler, el
número de conexiones al servidor escala con `workers × réplicas`, sin techo
predecible. PgBouncer intercala esas conexiones: la app abre y cierra
conexiones "baratas" contra PgBouncer, y PgBouncer mantiene un pool chico y
fijo de conexiones reales contra Postgres.

## Arquitectura

```
gunicorn (sync workers) → PgBouncer :6432 (pool_mode=transaction) → Postgres :5432
```

- `docker-compose.prod.yml` agrega el servicio `pgbouncer` (imagen
  `edoburu/pgbouncer:v1.25.2-p0`) y hace que `api` conecte a
  `pgbouncer:6432` en vez de `db:5432`.
- La configuración vive en `docker/pgbouncer/pgbouncer.ini`, versionada. Al
  montarla, el entrypoint de la imagen (que si no hay archivo genera uno
  desde variables `DATABASE_URL`/`DB_*`) no hace nada: usa el archivo tal
  cual está.
- `pool_mode = transaction`: una conexión de servidor se asigna a un cliente
  solo durante una transacción, no durante toda la sesión. Es el modo que
  soporta más clientes por conexión real, y es compatible con el código
  actual (ver "Qué no funciona" más abajo).

## Sizing — cómo se llegó a estos números

### `default_pool_size` (transacciones concurrentes de escritura, no RPS)

`IdempotentMutationMixin` (`apps/idempotency/mixins.py`) envuelve **todo**
`POST /movements/*` en un `atomic()`. Eso significa que cada venta, ingreso,
transferencia, etc. retiene una conexión de servidor durante **todo el
request**, no solo durante una query puntual. El pool hay que dimensionarlo
por escrituras concurrentes esperadas, no por requests/segundo totales.

Con Postgres en su default (`max_connections = 100`,
`superuser_reserved_connections = 3`), y un solo pool (una base × un
usuario):

```
default_pool_size (20) + reserve_pool_size (5) = 25 conexiones máx.
```

Deja 72 conexiones libres para acceso directo (migraciones, `pg_dump`, otros
servicios). **Son valores de arranque, no medidos.** Equipo D los va a
validar con carga real (`docs/infra/load-testing.md`) — si el escenario "hot
row" muestra esperas largas en `SHOW POOLS` sin que Postgres esté saturado,
subir `default_pool_size` primero.

### `max_client_conn` (api ↔ pgbouncer, no pgbouncer ↔ postgres)

Con `CONN_MAX_AGE = 0`, cada worker gunicorn sostiene como máximo una
conexión de cliente mientras atiende un request activo. La fórmula:

```
max_client_conn ≥ (réplicas × workers) + margen (healthchecks, admin console, cron)
```

Con 1 réplica y `WEB_CONCURRENCY=5` (ver `docker-compose.prod.yml`), el
mínimo real es 5; se dejó en 200 con margen generoso para escalar réplicas
sin tocar el `.ini`. Si el deploy real escala horizontalmente, recalcular.

### `query_wait_timeout` (15s) vs. `timeout` de gunicorn (30s)

El default de PgBouncer es 120s. Con eso, un worker de gunicorn se muere por
timeout **antes** de que PgBouncer le devuelva un error de "no hay pool
disponible" — el cliente recibe un 502/conexión cortada en vez de un error
limpio. `query_wait_timeout = 15` deja margen para que PgBouncer responda
antes que gunicorn mate al worker.

## Bootstrap (una sola vez, antes de levantar el stack)

### Autenticación: `auth_query`, no un `userlist.txt` por usuario

`auth_type = scram-sha-256` con `auth_query` evita duplicar la contraseña de
cada usuario de la app en `userlist.txt`: PgBouncer llama a una función SQL
que busca el verificador SCRAM directamente en `pg_shadow`, con un único
usuario dedicado (`pgbouncer_auth`) para ejecutar esa función.

1. **Crear el rol y la función.** `docker/postgres/initdb/01_pgbouncer_auth.sql`
   crea `pgbouncer_auth` (sin privilegios sobre tablas) y
   `public.user_lookup()` (`SECURITY DEFINER`, con `REVOKE ALL FROM PUBLIC`
   explícito para que solo `pgbouncer_auth` pueda ejecutarla).

   - En una base **nueva** (volumen `postgres_data` vacío), esto corre solo:
     `docker-compose.prod.yml` monta `docker/postgres/initdb/` en
     `/docker-entrypoint-initdb.d/`, y el entrypoint oficial de `postgres`
     ejecuta esos scripts en el primer arranque.
   - En una base **existente**, no corre solo. Aplicarlo a mano una vez:
     ```
     docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
       exec -T db psql -U stock_user -d stock_db < docker/postgres/initdb/01_pgbouncer_auth.sql
     ```

2. **Rotar la contraseña placeholder.** El script crea `pgbouncer_auth` con
   una contraseña de ejemplo (`CHANGE_ME_IMMEDIATELY`). Cambiarla antes de
   exponer el servicio:
   ```
   docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
     exec db psql -U stock_user -d stock_db -c \
     "ALTER ROLE pgbouncer_auth WITH PASSWORD '<secreto real>';"
   ```

3. **Generar `docker/pgbouncer/userlist.txt`.** No se versiona (está en
   `.gitignore`; ver `docker/pgbouncer/userlist.txt.example` para el
   formato). Generarlo desde `pg_shadow` después del paso 2:
   ```
   make pgb-userlist
   ```
   Este archivo solo contiene el verificador de `pgbouncer_auth` — nunca las
   contraseñas de los usuarios de la app, que `auth_query` resuelve en el
   momento.

4. Si `pgbouncer` ya estaba corriendo, reiniciarlo para que tome el archivo
   nuevo: `docker-compose -f docker-compose.yml -f docker-compose.prod.yml
   restart pgbouncer`.

## Acceso directo (bypass del pool)

Migraciones, `pg_dump` y comandos pesados de management **no** deben pasar
por PgBouncer: `CREATE INDEX CONCURRENTLY` (Equipo B) y otras operaciones de
DDL necesitan una conexión que no vaya a rotar de cliente a mitad de
transacción, y `pg_dump` no entiende de todos modos un alias de conexión de
Django.

El patrón elegido es pisar `DATABASE_URL` por variable de entorno en el
contenedor puntual que lo necesita, no un alias `direct` en `DATABASES` —
más simple y sin tocar `base.py`/`tests/test_settings.py`:

```
make prod-migrate   # ver el target en el Makefile
```

o a mano:

```
docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm -e DATABASE_URL=postgres://stock_user:stock_password@db:5432/stock_db \
  api python manage.py migrate
```

`pg_dump`/`pg_restore` (Equipo C) usan host y puerto directos
(`db`/`5432`), no una URL de Django en absoluto.

## Diagnóstico — consola de administración

Atajos (`make pgb-pools`, `make pgb-stats`, `make pgb-clients`) o a mano
contra la base virtual `pgbouncer`:

```
docker-compose -f docker-compose.yml -f docker-compose.prod.yml \
  exec pgbouncer psql -h 127.0.0.1 -p 6432 -U pgbouncer_auth pgbouncer -c "SHOW POOLS;"
```

### `SHOW POOLS`

| Columna | Qué mirar |
|---|---|
| `cl_active` / `cl_waiting` | Clientes activos vs. esperando un slot del pool. `cl_waiting` sostenido y creciente = pool subdimensionado o transacciones más largas de lo esperado. |
| `sv_active` / `sv_idle` | Conexiones reales a Postgres en uso / libres. `sv_active` pegado a `default_pool_size` = el pool está al límite. |
| `maxwait` | Segundos que lleva esperando el cliente más antiguo en cola. Si se acerca a `query_wait_timeout` (15s), va a empezar a fallar. |

### `SHOW STATS`

`avg_xact_time` (duración promedio de transacción) y `avg_wait_time`
(cuánto esperan los clientes por un slot). Un `avg_xact_time` alto en
`venta` es esperable (retiene la conexión todo el request, ver sizing
arriba); si `avg_wait_time` empieza a acercarse a `avg_xact_time`, el pool
está subdimensionado para la carga actual.

### `SHOW CLIENTS`

Quién está conectado y hace cuánto está esperando (`wait` en segundos por
fila) — útil para encontrar un cliente específico atascado, no solo el
agregado de `SHOW POOLS`.

### Errores típicos

| Error | Causa típica |
|---|---|
| `no more connections allowed (max_client_conn)` | Más clientes de los que `max_client_conn` permite — revisar `workers`/réplicas vs. el `.ini`. |
| Timeout / conexión cortada cerca de los 15s | `query_wait_timeout` alcanzado: el pool está saturado, no un problema de red. |
| Pool agotado con `sv_active` bajo pero `cl_waiting` alto | Transacciones más largas de lo esperado (revisar si algo quedó fuera del `atomic()` esperado, o una query lenta reteniendo la conexión). |

## Qué NO funciona en `pool_mode = transaction`

- `SET` de sesión que deba persistir entre transacciones.
- Advisory locks tomados fuera de una transacción (`pg_advisory_lock`, no
  `pg_advisory_xact_lock`) — no se usan en este proyecto.
- `LISTEN`/`NOTIFY` — no se usan en este proyecto.
- Cursores nombrados del lado servidor (`.iterator()` de Django) — por eso
  `DISABLE_SERVER_SIDE_CURSORS = True` en `config/settings/production.py`,
  aunque hoy nada los use.

Estado actual verificado: todo `select_for_update()` del código está dentro
de `transaction.atomic()`, no hay `.iterator()`, advisory locks ni
`LISTEN/NOTIFY` — el código es compatible con transaction pooling tal como
está.

## Pendiente / fuera de alcance de este entregable

- El puerto 5432 de `db` sigue publicado en el host incluso con el overlay
  de prod (Compose combina listas como `ports` entre archivos en vez de
  reemplazarlas). Cerrarlo requiere firewall a nivel de host/red, o separar
  `db` en un compose base distinto para dev y prod. Ver el comentario en
  `docker-compose.prod.yml`.
- Los valores de `pgbouncer.ini` son un punto de partida razonado, no
  medido. Re-tunear con los resultados de Equipo D
  (`docs/infra/load-testing.md`).
