"""
gunicorn.conf.py

Production-grade Gunicorn configuration for the stock management API.

Worker model: sync (pre-fork)
  Django views are CPU-bound (Argon2 hashing, DB queries with locking).
  The sync worker model is correct here. Async workers (gevent, eventlet)
  are for I/O-bound workloads and can introduce subtle bugs with
  Django's ORM transaction handling and select_for_update().

Worker count formula: 2 × CPU_COUNT + 1
  The +1 handles requests while other workers are waiting on the DB.
  With PostgreSQL's row-level locking (select_for_update), a worker
  can block briefly on a locked row. The extra worker keeps throughput
  steady during those blocks.
  Adjust CPU_COUNT below to match the production server's core count.

  multiprocessing.cpu_count() reads the HOST's core count, which is
  wrong the moment this runs in a container with a CPU limit narrower
  than the host (Docker --cpus, a Kubernetes cpu limit, ...) — it will
  happily compute a worker count the container is never allowed to use
  concurrently. Set WEB_CONCURRENCY explicitly for any real deploy
  target; the formula below only exists as a fallback for local /
  single-core environments where nothing has set it.

  This number is also PgBouncer's other input: pgbouncer.ini's
  max_client_conn is sized off (replicas × workers × threads) + margin
  — see that file's own comment. Changing `workers` (or WEB_CONCURRENCY)
  without revisiting max_client_conn can silently undersize the pool.
"""

import multiprocessing
import os

# ------------------------------------------------------------------
# Binding
# ------------------------------------------------------------------
bind = "0.0.0.0:8000"
backlog = 64  # Max pending connections in the OS queue

# ------------------------------------------------------------------
# Workers
# ------------------------------------------------------------------
_default_workers = multiprocessing.cpu_count() * 2 + 1
workers = int(os.environ.get("WEB_CONCURRENCY", _default_workers))
worker_class = "sync"
threads = 1  # One thread per sync worker; Django is not thread-safe by default

# ------------------------------------------------------------------
# Timeouts
# ------------------------------------------------------------------
timeout = 30  # Worker killed if no response within 30s
# Must stay above pgbouncer.ini's query_wait_timeout (15s): a request
# stuck waiting for a pooled server connection should get a clean
# PgBouncer error well before gunicorn SIGKILLs the worker mid-request.
graceful_timeout = 20  # Workers get 20s to finish current requests on restart
keepalive = 5  # Seconds to keep idle HTTP/1.1 connections alive

# ------------------------------------------------------------------
# Request limits (defense against slowloris and large payloads)
# ------------------------------------------------------------------
max_requests = 1000  # Worker restarts after N requests (prevents memory leaks)
max_requests_jitter = 200  # Random jitter so all workers don't restart simultaneously
limit_request_line = 4096  # Max size of HTTP request line in bytes
limit_request_fields = 100  # Max number of HTTP headers

# ------------------------------------------------------------------
# Logging — stdout/stderr so Docker captures logs natively
# ------------------------------------------------------------------
accesslog = "-"  # stdout
errorlog = "-"  # stderr
loglevel = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ------------------------------------------------------------------
# Process naming
# ------------------------------------------------------------------
proc_name = "stock_api"
