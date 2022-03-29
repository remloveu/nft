import os
from threading import Thread


def func1():
    os.system('gunicorn -c config.py heco:server')


def func2():
    os.system('python3 m_thread.py')


def func3():
    os.system('python3 s_thread.py')


t1 = Thread(target=func1)
t2 = Thread(target=func2)
t3 = Thread(target=func3)
t1.setDaemon(True)
t2.setDaemon(True)
t3.setDaemon(True)
t1.start()
t2.start()
t3.start()
t1.join()
t2.join()
t3.join()