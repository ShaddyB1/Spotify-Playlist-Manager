import multiprocessing

bind = "0.0.0.0:10000"
workers = multiprocessing.cpu_count() * 2 + 1
threads = 2
timeout = 300  
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
worker_class = "sync"  
accesslog = "-"
loglevel = "info"
graceful_timeout = 300
worker_connections = 1000
