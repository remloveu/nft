import os
from threading import Thread

def func1():
    os.system('gunicorn -c config.py heco:server')

def func2():
    os.system('python3 thread.py')


t1 = Thread(target=func1)
t1.start()
t2 = Thread(target=func2)
t2.start()