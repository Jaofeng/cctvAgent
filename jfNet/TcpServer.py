#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import time
import traceback
import threading
import socket
from . import EventTypes, SocketError
import TcpClient


class TcpServer:
    """以 TCP 為連線基礎的 Socket Server
    `host` : `tuple(ip, Port)` - 提供連線的 IPv4 位址與通訊埠號
    """
    _host:tuple = None
    _socket:socket.socket = None
    _acceptThread:threading.Thread = None
    _events:dict = {
        EventTypes.STARTED: None,
        EventTypes.STOPED: None,
        EventTypes.CONNECTED: None,
        EventTypes.DISCONNECT: None,
        EventTypes.RECEIVED: None,
        EventTypes.SENDED: None,
        EventTypes.SENDFAIL: None
    }
    _stop:bool = False
    _clients:dict = {}
    _name:str = ''

    def __init__(self, host:tuple):
        self._host = host
        self._name = '{}:{}'.format(*(host))
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Public Properties
    @property
    def host(self) -> tuple:
        """回傳本端提供連線的通訊埠號
        回傳:
        `tuple(ip, port)`
        """
        return self._host

    @property
    def isAlive(self) -> bool:
        """取得伺服器是否處於等待連線中
        回傳:
        `True` / `False`
            *True* : 等待連線中
            *False* : 停止等待
        """
        return self._acceptThread and self._acceptThread.isAlive()

    @property
    def clients(self) -> dict:
        """傳回已連接的連線資訊
        回傳:
            `dictionary{ tuple(ip, port) : <TcpClient>, ... }`
        """
        return self._clients.copy()

    # Public Methods
    def start(self):
        """啟動 TcpServer 伺服器，開始等待遠端連線
        引發錯誤:
            `Exception` -- 回呼的錯誤函式
        """
        try:
            self._socket.bind(self._host)
        except socket.error as ex:
            if ex.errno == 48:
                raise SocketError(1005)
            else:
                raise ex
        self._socket.listen(5)
        self._acceptThread = threading.Thread(target=self._accept_client)
        self._acceptThread.setDaemon(True)
        self._acceptThread.start()
        now = time.time()
        while not self._acceptThread.isAlive and (time.time() - now) <= 1:
            time.sleep(0.1)
        if self.isAlive and self._events[EventTypes.STARTED]:
            self._events[EventTypes.STARTED](self)

    def stop(self):
        """停止等待遠端連線
        """
        self._stop = True
        self.close()
        self._socket.close()
        self._socket = None
        if self._acceptThread:
            self._acceptThread.join(1.5)

    def bind(self, key:str, evt=None):
        """綁定回呼(callback)函式
        具名參數:
            `key` `str` -- 回呼事件代碼；為避免錯誤，建議使用 *EventTypes* 列舉值
            `evt` `def` -- 回呼(callback)函式
        引發錯誤:
            `KeyError` -- 回呼事件代碼錯誤
            `TypeError` -- 型別錯誤，必須為可呼叫執行的函式
        """
        if key not in self._events:
            raise KeyError('key:\'{}\' not found!'.format(key))
        if evt is not None and not callable(evt):
            raise TypeError('evt:\'{}\' is not a function!'.format(evt))
        self._events[key] = evt

    def send(self, data, remote=None):
        """發送資料至遠端
        傳入參數:
            `data` `str` -- 欲傳送到遠端的資料
        具名參數:
            `remote` `tuple(ip, port)` -- 欲傳送的遠端連線；未傳入時，則發送給所有連線
        引發錯誤:
            `KeyError` -- 遠端連線不存在
            `TypeError` -- 遠端連線不存在
            `jfSocket.SocketError` -- 遠端連線已斷開
            `Exception` -- 其他錯誤
        """
        if remote:
            if remote not in self._clients:
                raise KeyError()
            elif self._clients[remote] is None:
                raise TypeError()
            elif not self._clients[remote].isAlive:
                raise SocketError(1001)
            self._clients[remote].send(data)
        else:
            for x in self._clients:
                self._clients[x].send(data)

    def close(self, remote=None):
        """關閉遠端連線
        具名參數:
            `remote` `tuple(ip, port)` -- 欲關閉的遠端連線；未傳入時，則關閉所有連線
        """
        if remote is not None:
            if remote not in self._clients:
                return
            elif self._clients[remote] or not self._clients[remote].isAlive:
                del self._clients[remote]
            else:
                self._clients[remote].close()
        else:
            for x in self._clients:
                if self._clients[x]:
                    self._clients[x].close()
                del self._clients[x]

    # Private Methods
    def _onClientDisconnect(self, *args):
        if self._clients[args[2]]:
            del self._clients[args[2]]
        if self._events[EventTypes.DISCONNECT]:
            self._events[EventTypes.DISCONNECT](*(args))

    def _accept_client(self):
        # 使用非阻塞方式等待連線，逾時時間為 1 秒
        self._socket.settimeout(1)
        while not self._stop:
            try:
                client, addr = self._socket.accept()
            except socket.timeout:
                # 等待連線逾時，再重新等待
                continue
            except:
                # except (socket.error, IOError) as ex:
                # 先攔截並顯示，待未來確定可能會發生的錯誤再進行處理
                print(traceback.format_exc())
                break
            if self._stop:
                try:
                    client.close()
                except:
                    pass
                break
            clk = TcpClient.TcpClient(client)
            clk.bind(key=EventTypes.RECEIVED, evt=self._events[EventTypes.RECEIVED])
            clk.bind(key=EventTypes.DISCONNECT, evt=self._onClientDisconnect)
            clk.bind(key=EventTypes.SENDED, evt=self._events[EventTypes.SENDED])
            clk.bind(key=EventTypes.SENDFAIL, evt=self._events[EventTypes.SENDFAIL])
            self._clients[addr] = clk
            if self._events[EventTypes.CONNECTED] is not None:
                self._events[EventTypes.CONNECTED](clk, self._host, addr)
        if self._events[EventTypes.STOPED] is not None:
            self._events[EventTypes.STOPED](self)
