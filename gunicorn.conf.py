
import multiprocessing


bind = "0.0.0.0:8000"
backlog = 2048


workers = multiprocessing.cpu_count() * 2 + 1
worker_class = "gevent"
threads = 4
worker_connections = 1000
timeout = 300
keepalive = 2


graceful_timeout = 300
timeout = 300

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"


proc_name = "spotify_playlist_manager"


keyfile = None
certfile = None

# Server mechanics
daemon = False
pidfile = None
umask = 0
user = None
group = None
tmp_upload_dir = None


def child_exit(server, worker):
    server.log.info("Worker exited: %s", worker.pid)
