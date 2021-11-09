import os
from threading import Thread

def func1():
    os.system('gunicorn -c config.py heco:server')

def func2():
    os.system('python3 log_loop.py')

def func3():
    os.system('python3 update.py')

t1 = Thread(target=func1)
t1.start()
t2 = Thread(target=func2)
t2.start()
t3 = Thread(target=func3)
t3.start()