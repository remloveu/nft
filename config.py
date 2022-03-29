import multiprocessing
import os

if not os.path.exists('log'):
    os.mkdir('log')

lock = multiprocessing.Lock()

def pre(worker, req):
    req.headers.append(('FLASK_LOCK', lock))


pre_request = pre
workers = 32
threads = 2
bind = '0.0.0.0:8888'
timeout = 50
backlog = 512
daemon = False
#reload = True
worker_class = 'gevent'
worker_connections = 2000
access_log_format = '%(t)s %(p)s %(h)s "%(r)s" %(s)s %(L)s %(b)s "%(f)s" "%(a)s"'
accesslog = 'log/access.log'
errorlog = 'log/error.log'
