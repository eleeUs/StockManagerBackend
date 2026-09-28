# Roadmap — Fases 7 a 10 (post Phase 6)

## Contexto

Las Fases 1–6 ya cubren, y en varios puntos superan, un plan de desarrollo
estándar de nivel MVP para un sistema de stock multi-sucursal (modelos,
capa de servicios, permisos, concurrencia, testing, reportes, CI/CD,
hardening de seguridad).

Este roadmap cubre lo que le falta al proyecto para acercarse a un sistema
de nivel producción real: valorización de inventario, idempotencia,
observabilidad y escala. Las fases son modulares — no es necesario
completarlas todas; se pueden priorizar según el objetivo (portfolio vs.
producción real).

**Orden de prioridad:** valor de negocio → integridad de datos →
producción/operación → calidad y escala.

---

## Fase 7 — Valorización, proveedores y alertas de stock

**Objetivo:** que el sistema responda "¿cuánto vale mi inventario?" y
"¿qué necesito reponer?" sin intervención manual.

### Alcance

- Agregar `cost_price` y `sale_price` a `Product` (`DecimalField`, mismo
  patrón que `Stock.quantity`).
- Nuevo modelo `Supplier` (nombre, contacto, activo) + FK opcional en el
  movimiento de `ingreso`.
- Nuevo campo `reorder_point` (punto de reposición configurable por
  producto o por combinación producto+sucursal, a definir según si el
  umbral es global o local).
- Nuevo reporte: `GET /api/v1/reports/stock/valuation/` — valor total de
  inventario (`quantity * cost_price`) por sucursal y por producto.
- Comando de management `check_low_stock` — recorre `Stock` vs
  `reorder_point` y loguea/webhookea alertas (pensado para correr por cron,
  sin necesidad de Celery).
- Migraciones, tests, y actualización de `BUSINESS_RULES.md` documentando
  las nuevas reglas (quién puede fijar precios y proveedores, cómo se
  calcula el punto de reposición).

---

## Fase 8 — Idempotencia y auditoría extendida

**Objetivo:** cerrar los huecos de integridad de datos antes de que se
conviertan en incidentes reales (reintentos de red duplicando ventas,
cambios sin trazabilidad en catálogo/usuarios).

### Alcance

- Middleware o decorator de idempotencia: header `Idempotency-Key` en los
  endpoints `POST /movements/*`. Se guarda la respuesta original asociada
  a la key y se devuelve la misma respuesta si se repite dentro de una
  ventana de tiempo, sin re-ejecutar el movimiento.
- Integrar auditoría de cambios (`django-simple-history` o un `AuditLog`
  propio append-only, consistente con el patrón ya usado en
  `StockMovement`) para `Product`, `Branch` y `User`.
- Tests de duplicación: reintentar el mismo `POST /movements/venta/` con
  la misma `Idempotency-Key` no debe duplicar el movimiento ni descontar
  stock dos veces.

---

## Fase 9 — Observabilidad y hardening de CI

**Objetivo:** que un error en producción se detecte en minutos, no cuando
un usuario se queja.

### Alcance

- Integrar Sentry (o equivalente) vía `SENTRY_DSN` en `config/settings/production.py`.
- Separar el health check actual en `/health/live/` (liveness) y
  `/health/ready/` (readiness) — relevante si el sistema llega a correr
  en un orquestador tipo Kubernetes.
- Agregar `pip-audit` (dependencias vulnerables) y `gitleaks` (secretos
  filtrados) como jobs adicionales en `.github/workflows/ci.yml`, en
  paralelo a `lint` y `test`.
- Agregar `pytest-cov` con un umbral mínimo de cobertura que falle el
  build si baja de ese umbral.
- Agregar configuración de `pre-commit` con `ruff` (reusando la config
  ya existente en `pyproject.toml`) para que el lint corra antes del
  commit, no solo en CI.

---

## Fase 10 — Escala y operación

**Objetivo:** preparar el sistema para volumen real de datos y tráfico,
no solo para que funcione correctamente.

### Alcance

- Sumar `PgBouncer` en `docker-compose.prod.yml`, entre gunicorn y
  PostgreSQL, para pooling de conexiones (cada worker sync de gunicorn
  abre su propia conexión; sin pooling esto escala mal).
- Migrar los índices sobre tablas de alto volumen (`StockMovement` en
  particular) a `RunSQL` con `CREATE INDEX CONCURRENTLY` en vez de
  `AddIndex` estándar, para no bloquear escrituras durante la creación
  del índice en producción.
- Documentar un runbook de backup/restore (`pg_dump` programado +
  procedimiento de restore probado, no solo asumido).
- Test de carga básico (`locust` o `k6`) sobre `POST /movements/venta/`
  para validar que el locking (`select_for_update`) no se vuelve cuello
  de botella bajo concurrencia real, no solo bajo los 2 threads que
  cubren los tests actuales.

---

## Resumen ejecutivo

| Fase | Foco | Impacto |
|---|---|---|
| 7 | Valorización, proveedores, alertas | Alto valor de negocio, visible y fácil de explicar |
| 8 | Idempotencia, auditoría extendida | Integridad de datos — previene incidentes silenciosos |
| 9 | Observabilidad, hardening de CI | Calidad de ingeniería, valorado en revisión de código |
| 10 | Escala y operación | Relevante solo si el sistema va a manejar volumen/tráfico real |

Recomendación: si el objetivo es portfolio, priorizar Fase 7 (impacto de
negocio tangible) y Fase 9 en su versión mínima (Sentry + pre-commit).
Si el objetivo es producción real, seguir el orden completo.
