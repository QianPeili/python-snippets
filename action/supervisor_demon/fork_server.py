#coding:utf-8
import os
import time
import sys
import signal
import threading
import selectors

from fcntl import fcntl
from fcntl import F_SETFL, F_GETFL

from rpc_server import ForkXMLRPCServer


class RunObj(object):                   # 任务运行类
    def run(self):
        while True:                     # 循环执行任务
            pid = os.getpid()
            print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())+ " " + str(pid) +" sub pid \n")
            time.sleep(5)


# def make_pipes():
#     """ Create pipes for parent to child stdin/stdout/stderr
#     communications.  Open fd in nonblocking mode so we can read them
#     in the mainloop without blocking """
#     pipes = {}
#     try:
#         pipes['child_stdin'], pipes['stdin'] = os.pipe()                    # 生成管道
#         pipes['stdout'], pipes['child_stdout'] = os.pipe()
#         pipes['stderr'], pipes['child_stderr'] = os.pipe()
#         for fd in (pipes['stdout'], pipes['stderr'], pipes['stdin']):
#             fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | os.O_NDELAY)            # 设置文件描述符状态，使该管道成为非阻塞模式
#         return pipes
#     except OSError:
#         raise

def close_fd(fd):
    os.close(fd)

def daemonize():
    print("fork")
    pid = os.fork()

    if pid:
        print("this is parent process")
        sys.exit(0)
    else:
        print("sub process")
        os.chdir(".")
        os.setsid()
        os.umask(0)
        fd = open("/dev/null", "a+")
        os.dup2(fd.fileno(), 0)
        os.dup2(fd.fileno(), 1)
        os.dup2(fd.fileno(), 2)
        fd.close()

SUB_RUNNING = 1                         # 运行状态
SUB_STOP = 0                            # 停止状态


# 自行定义的任务类
class SubSpwn(object):
    pid = 0                             # 初始Pid为0
    status = SUB_STOP                   # 初始状态为停止状态

    def __init__(self, name):
        self.name = name

    def dup2(self, frm, to):
        return os.dup2(frm, to)

    def spwn(self):
        # self.pipes = make_pipes()       # 通过管道重定向输入输出等

        pid = os.fork()                 # 生成子进程
        if pid:                         # pid大于0，此时父进程执行
            self.pid = pid
            self.status = SUB_RUNNING
            print("SubSpwn pid", pid)
            # for fdname in ('child_stdin', 'child_stdout', 'child_stderr'):
            #     close_fd(self.pipes[fdname])
            return 'done'                  # 返回子进程的Pid

        fd = open("process_%s.log" % self.name, "a+")        # 保护输入输出异常
        os.dup2(fd.fileno(), 0)     # 重定向标准输入
        os.dup2(fd.fileno(), 1)     # 重定向标准输出
        os.dup2(fd.fileno(), 2)     # 重定向标准错误输出
        fd.close()
        try:
            r = RunObj()
            r.run()
        finally:
            os._exit(127)                                   # 执行完毕后退出


class Control(ForkXMLRPCServer):                                # 运行的server即完成rpc通信也完成对子进程的监控与检查
    def __init__(self, *args, **kwargs):
        ForkXMLRPCServer.__init__(self, *args, **kwargs)
        daemonize()
        self.sub = [SubSpwn("spwn1"), SubSpwn("spwn2")]         # 默认开启了两个任务进程，可自行定义
        print("sub spwn")
        for sub in self.sub:
            sub.spwn()                                          # 任务进程开始运行

    def check_process(self):                                    # 检查子进程的运行状态
        pid = "pid"
        status = "status"
        try:
            pid, status = os.waitpid(-1, os.WNOHANG)            # waitpid的参数为-1,表示等待任何一个子进程，os.WNOHANG表示有进程退出则返回该进程Pid,没有则立即返回
            print("pid: {}, status: {}".format(pid, status))
            if pid != 0:
                with open("control.txt", "a") as f:
                    f.write("pid: {}, status: {}".format(pid, status) + "\n")
            for sub in self.sub:
                if sub.pid == pid and sub.status == SUB_RUNNING:  # 检查如果退出的进程是运行状态则立刻重启该进程
                    sub.spwn()
        except os.error:
            print("os error:", os.error)
            with open("control3.txt", "a") as f:
                f.write("pid: {}, status: {}".format(pid, status) + "\n")

        # self.read_pipes()                                       # 读管道数据

    def start_all(self):                                        # rpc函数，开启所有任务
        res = []
        for sub in self.sub:
            if sub.status == SUB_STOP:
                sub.spwn()
                res.append(sub.name + "already start")
            else:
                res.append(sub.name + ":" + str(sub.pid) + "already start")
        return "\n".join(res)

    def start_one(self, name):                                  # rpc函数，开启一个任务
        res = " no sub "
        for sub in self.sub:
            if name == sub.name and sub.status == SUB_STOP:
                sub.spwn()
                res = sub.name + ":" + str(sub.pid) + "-- now start"
                return res
        return res

    def stop_all(self):                                         # rpc函数，停止所有任务
        res = []
        for sub in self.sub:
            sub.status = SUB_STOP
            os.kill(sub.pid, signal.SIGTERM)
            res.append(sub.name + "already stop")
        return "\n".join(res)

    def stop_one(self, name):                                   # rpc函数，停止一个任务
        for sub in self.sub:
            if name == sub.name and sub.status == SUB_RUNNING:
                sub.status = SUB_STOP
                os.kill(sub.pid, signal.SIGTERM)
                res = sub.name + ": stop ****"
                return res
        res = "none sub stop or sub name"
        return res

    def status(self):                                           # rpc函数，显示当前任务状态
        res = []
        for sub in self.sub:
            res.append(sub.name + ":" + str(sub.status))
        return "\n".join(res)

    def exit(self):                                             # 主进程退出
        pid = os.getpid()
        for sub in self.sub:
            if sub.status == SUB_RUNNING:
                sub.status = SUB_STOP
                os.kill(sub.pid, signal.SIGTERM)
        t = threading.Thread(target=kill_self, args=(pid, ))    # 使用线程退出，以免在杀死自己后无数据返回
        t.start()
        return "exit ok:" + str(pid)


# 在线程中杀死自己退出
def kill_self(pid):
    time.sleep(3)
    os.kill(pid, signal.SIGTERM)

if __name__ == '__main__':
    server = Control(("127.0.0.1", 8003))

    def add(x, y):
        return x+y

    def sub(x, y):
        return x-y
    server.register_multicall_functions()
    server.register_function(add, "add")
    server.register_function(sub, "sub")
    server.register_function(server.status, "status")
    server.register_function(server.stop_all, "stop_all")
    server.register_function(server.start_all, "start_all")
    server.register_function(server.stop_one, "stop_one")
    server.register_function(server.start_one, "start_one")
    server.register_function(server.exit, "exit")
    server.serve_forever()