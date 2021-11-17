import os
from threading import Thread

def func1():
    os.system('gunicorn -c config.py heco:server')

def func2():
    os.system('python3 thread.py')


t1 = Thread(target=func1)
t2 = Thread(target=func2)
t1.setDaemon(True)
t2.setDaemon(True)
t1.start()
t2.start()
t1.join()
t2.join()