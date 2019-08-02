#! /usr/bin/env python3
# # -*- coding: UTF-8 -*-

import traceback
import socket
import threading
from . import EventTypes, SocketError


class TcpClient:
    """用於定義可回呼的 TCP 連線型態的 Socket Client
    具名參數:
        `socket` `socket` -- 承接的 Socket 類別，預設為 `None`
        `evts` `dict{str:def,...}` -- 回呼事件定義，預設為 `None`
    """
    _socket:socket.socket = None
    _events:dict = {
        EventTypes.CONNECTED: None,
        EventTypes.DISCONNECT: None,
        EventTypes.RECEIVED: None,
        EventTypes.SENDED: None,
        EventTypes.SENDFAIL: None
    }
    _handler:threading.Thread = None
    _host:tuple = None
    _stop:bool = False
    _remote:tuple = None
    recvBuffer:input = 256

    def __init__(self, socket: socket.socket = None):
        if socket and isinstance(socket, socket.socket):
            self._assign(socket)

    def __del__(self):
        self.close()

    # Public Properties
    @property
    def isAlive(self) -> bool:
        """取得目前是否正處於連線中
        回傳:
        `True` / `False`
            *True* : 連線中
            *False* : 連線已斷開
        """
        return self._handler and self._handler.isAlive()

    @property
    def host(self) -> tuple:
        """回傳本端的通訊埠號
        回傳:
        `tuple(ip, port)`
        """
        return self._host

    @property
    def remote(self) -> tuple:
        """回傳遠端伺服器的通訊埠號
        回傳:
        `tuple(ip, port)`
        """
        return self._remote

    # Public Methods
    def connect(self, host:tuple):
        """連線至遠端伺服器
        傳入參數:
            `host` `tuple(ip, port)` - 遠端伺服器連線位址與通訊埠號
        引發錯誤:
            `jfSocket.SocketError` -- 連線已存在
            `socket.error' -- 連線時引發的錯誤
            `Exception` -- 回呼的錯誤函式
        """
        assert isinstance(host, tuple) and isinstance(host[0], str) and isinstance(host[1], int),\
            'host must be tuple(str, int) type!!'
        if self.isAlive:
            raise SocketError(1000)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.connect(host)
        self._assign(self._socket)
        if self._events[EventTypes.CONNECTED]:
            self._events[EventTypes.CONNECTED](self, self._host, self._remote)

    def bind(self, key=None, evt=None):
        """綁定回呼(callback)函式
        傳入參數:
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

    def close(self):
        """關閉與遠端伺服器的連線"""
        self._stop = True
        if self._socket:
            self._socket.close()
        del self._socket
        if self._handler:
            self._handler.join(2.5)
        del self._handler

    def send(self, data):
        """發送資料至遠端伺服器
        傳入參數:
            `data` `str` -- 欲傳送到遠端的資料
        引發錯誤:
            `jfSocket.SocketError` -- 遠端連線已斷開
            `Exception` -- 回呼的錯誤函式
        """
        if not self.isAlive:
            raise SocketError(1001)
        try:
            self._socket.send(data)
        except Exception as e:
            if self._events[EventTypes.SENDFAIL]:
                self._events[EventTypes.SENDFAIL](self, data, e)
        else:
            if self._events[EventTypes.SENDED]:
                self._events[EventTypes.SENDED](self, data)

    # Private Methods
    def _assign(self, socket:socket.socket):
        self._socket = socket
        self._host = socket.getsockname()
        self._remote = socket.getpeername()
        self._handler = threading.Thread(target=self._receiverHandler, args=(socket,))
        self._stop = False
        self._handler.daemon = True
        self._handler.start()

    def _receiverHandler(self, client):
        # 使用非阻塞方式等待資料，逾時時間為 2 秒
        client.settimeout(2)
        while not self._stop:
            try:
                data = client.recv(self.recvBuffer)
            except socket.timeout:
                # 等待資料逾時，再重新等待
                if self._stop:
                    break
                else:
                    continue
            except:
                # 先攔截並顯示，待未來確定可能會發生的錯誤再進行處理
                print(traceback.format_exc())
                break
            if not data:
                # 空資料，認定遠端已斷線
                break
            else:
                # Received Data
                if len(data) == 0:
                    # 空資料，認定遠端已斷線
                    break
                elif len([x for x in data if ord(x) == 0x04]) == len(data):
                    # 收到 EOT(End Of Transmission, 傳輸結束)，則表示已與遠端中斷連線
                    break
                if self._events[EventTypes.RECEIVED]:
                    self._events[EventTypes.RECEIVED](self, data)
        if self._events[EventTypes.DISCONNECT]:
            self._events[EventTypes.DISCONNECT](self, self.host, self.remote)
