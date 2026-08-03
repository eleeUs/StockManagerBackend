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
"""
import multiprocessing

# ------------------------------------------------------------------
# Binding
# ------------------------------------------------------------------
bind    = "0.0.0.0:8000"
backlog = 64   # Max pending connections in the OS queue

# ------------------------------------------------------------------
# Workers
# ------------------------------------------------------------------
workers      = multiprocessing.cpu_count() * 2 + 1
worker_class = "sync"
threads      = 1   # One thread per sync worker; Django is not thread-safe by default

# ------------------------------------------------------------------
# Timeouts
# ------------------------------------------------------------------
timeout    = 30    # Worker killed if no response within 30s
graceful_timeout = 20  # Workers get 20s to finish current requests on restart
keepalive  = 5     # Seconds to keep idle HTTP/1.1 connections alive

# ------------------------------------------------------------------
# Request limits (defense against slowloris and large payloads)
# ------------------------------------------------------------------
max_requests        = 1000   # Worker restarts after N requests (prevents memory leaks)
max_requests_jitter = 200    # Random jitter so all workers don't restart simultaneously
limit_request_line  = 4096   # Max size of HTTP request line in bytes
limit_request_fields = 100   # Max number of HTTP headers

# ------------------------------------------------------------------
# Logging — stdout/stderr so Docker captures logs natively
# ------------------------------------------------------------------
accesslog  = "-"      # stdout
errorlog   = "-"      # stderr
loglevel   = "info"
access_log_format = '%(h)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ------------------------------------------------------------------
# Process naming
# ------------------------------------------------------------------
proc_name = "stock_api"
