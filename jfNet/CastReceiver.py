#! /usr/bin/env python3
# # -*- coding: UTF-8 -*-

import time, sys, errno, struct, threading, socket
from . import EventTypes, SocketError


class CastReceiver:
    '''建立多播監聽器(Multicast)類別
    傳入參數:
        `port` `int` -- 欲監聽的通訊埠號
    '''
    def __init__(self, host):
        if isinstance(host, int):
            self.__host: tuple = ('', host)
        elif isinstance(host, tuple):
            self.__host: tuple = host
        self.__events: dict = {
            EventTypes.STARTED: None,
            EventTypes.STOPED: None,
            EventTypes.RECEIVED: None,
            EventTypes.JOINED_GROUP: None,
            EventTypes.SENDED: None,
            EventTypes.SENDFAIL: None
        }
        self.__socket: socket.socket = None
        self.__groups: list = []
        self.__stop = False
        self.__receiveHandler: threading.Thread = None
        self.__reuseAddr = True
        self.__reusePort = False
        self.recvBuffer = 256

    # Public Properties
    @property
    def groups(self) -> list:
        '''取得已註冊監聽的群組IP
        回傳: `list(str, ...)` -- 已註冊的IP
        '''
        return self.__groups[:]

    @property
    def host(self) -> tuple:
        '''回傳本端的通訊埠號
        回傳: `tuple(ip, port)`
        '''
        return self.__host

    @property
    def isAlive(self) -> bool:
        '''取得多播監聽器是否處於監聽中
        回傳: `boolean`
            *True* : 等待連線中
            *False* : 停止等待
        '''
        return self.__receiveHandler and self.__receiveHandler.is_alive()

    @property
    def reuseAddr(self) -> bool:
        '''取得是否可重複使用 IP 位置
        回傳: `boolean`
            *True* : 可重複使用
            *False* : 不可重複使用
        '''
        return self.__reuseAddr

    @reuseAddr.setter
    def reuseAddr(self, value: bool):
        '''設定是否可重複使用 IP 位置
        '''
        if not isinstance(value, bool):
            raise TypeError()
        self.__reuseAddr = value
        if self.__socket:
            self.__socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 if self.__reuseAddr else 0
            )

    @property
    def reusePort(self) -> bool:
        '''取得是否可重複使用通訊埠位
        回傳: `boolean`
            *True* : 可重複使用
            *False* : 不可重複使用
        '''
        return self.__reusePort

    @reusePort.setter
    def reusePort(self, value:bool):
        '''設定是否可重複使用通訊埠位
        '''
        if not isinstance(value, bool):
            raise TypeError()
        self.__reusePort = value
        if self.__socket and not sys.platform.startswith('win'):
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1 if self.__reusePort else 0)

    # Public Methods
    def start(self):
        '''啟動多播監聽伺服器
        引發錯誤:
            `socket.error` -- 監聽 IP 設定錯誤
            `Exception` -- 回呼的錯誤函式
        '''
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        # self._socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', 32))
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1 if self.__reuseAddr else 0)
        if not sys.platform.startswith('win'):
            self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1 if self.__reusePort else 0)
        try:
            self.__socket.bind(self.__host)
        except socket.error as ex:
            if ex.errno == 48:
                raise SocketError(1005)
            else:
                raise ex
        self.__receiveHandler = threading.Thread(target=self.__receive_handler)
        self.__receiveHandler.setDaemon(True)
        self.__receiveHandler.start()
        now = time.time()
        while not self.__receiveHandler.isAlive and (time.time() - now) <= 1:
            time.sleep(0.1)
        for x in self.__groups:
            self.__doAddMembership(x)
        if self.isAlive and self.__events[EventTypes.STARTED]:
            self.__events[EventTypes.STARTED](self)

    def stop(self):
        '''停止監聽
        '''
        self.__stop = True
        if self.__socket:
            for x in self.__groups:
                self.__doDropMembership(x)
            self.__socket.close()
        self.__socket = None
        if self.__receiveHandler is not None:
            self.__receiveHandler.join(1)
        self.__receiveHandler = None

    def joinGroup(self, ips:list):
        '''加入監聽IP
        傳入參數:
            `ips` `list(str, ...)` -- 欲監聽的 IP 陣列 list
        引發錯誤:
            `SocketError` -- 監聽的 IP 錯誤或該 IP 已在監聽中
            `socket.error` -- 無法設定監聽 IP 
        '''
        for x in ips:
            v = socket.inet_aton(x)[0]
            if isinstance(v, str):
                v = ord(v)
            if v not in range(224, 240):
                raise SocketError(1004)
            if x in self.__groups:
                raise SocketError(1002)
            self.__groups.append(x)
            if self.__socket:
                self.__doAddMembership(x)

    def dropGroup(self, ips:list):
        '''移除監聽清單中的 IP
        `注意`：如在監聽中移除IP，需重新啟動
        傳入參數:
            `ips` `list(str, ...)` -- 欲移除監聽的 IP 陣列 list
        引發錯誤:
            `SocketError` -- 欲移除的 IP 錯誤或該 IP 不存在
        '''
        for x in ips:
            v = socket.inet_aton(x)[0]
            if isinstance(v, str):
                v = ord(v)
            if v not in range(224, 240):
                raise SocketError(1004)
            if x not in self.__groups:
                raise SocketError(1003)
            self.__groups.remove(x)
            if self.__socket:
                self.__doDropMembership(x)

    def bind(self, key:str = None, evt=None):
        '''綁定回呼(callback)函式
        傳入參數:
            `key` `str` -- 回呼事件代碼；為避免錯誤，建議使用 *EventTypes* 列舉值
            `evt` `def` -- 回呼(callback)函式
        引發錯誤:
            `KeyError` -- 回呼事件代碼錯誤
            `TypeError` -- 型別錯誤，必須為可呼叫執行的函式
        '''
        if key not in self.__events:
            raise KeyError('key:"{}" not found!'.format(key))
        if evt is not None and not callable(evt):
            raise TypeError('evt:"{}" is not a function!'.format(evt))
        self.__events[key] = evt

    def send(self, remote:tuple, data):
        """以 UDP 方式發送資料
        傳入參數:
            `remote` `tuple(ip, port)` -- 遠端位址
            `data` `str or bytearray` -- 欲傳送的資料
        引發錯誤:
            `jfSocket.SocketError` -- 遠端連線已斷開
            `Exception` -- 回呼的錯誤函式
        """
        ba = None
        if isinstance(data, str):
            data = data.encode('utf-8')
            ba = bytearray(data)
        elif isinstance(data, bytearray) or isinstance(data, bytes):
            ba = data[:]
        try:
            self.__socket.sendto(ba, (remote[0], int(remote[1])))
        except Exception as e:
            if self.__events[EventTypes.SENDFAIL]:
                self.__events[EventTypes.SENDFAIL](self, ba, remote, e)
        else:
            if self.__events[EventTypes.SENDED]:
                self.__events[EventTypes.SENDED](self, ba, remote)

    # Private Methods
    def __receive_handler(self):
        # 使用非阻塞方式等待資料，逾時時間為 2 秒
        self.__socket.settimeout(0.5)
        while not self.__stop:
            try:
                data, addr = self.__socket.recvfrom(self.recvBuffer)
            except socket.timeout:
                # 等待資料逾時，再重新等待
                if self.__stop:
                    break
            except OSError:
                break
            except Exception:
                # 先攔截並顯示，待未來確定可能會發生的錯誤再進行處理
                import traceback
                print(traceback.format_exc())
                break
            else:
                if data and len(data) != 0:
                    # Received Data
                    if self.__events[EventTypes.RECEIVED]:
                        self.__events[EventTypes.RECEIVED](self, data, self.__socket.getsockname(), addr)
        if self.__events[EventTypes.STOPED]:
            self.__events[EventTypes.STOPED](self)

    def __doAddMembership(self, ip):
        try:
            mreq = struct.pack('4sL', socket.inet_aton(ip), socket.INADDR_ANY)
            self.__socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq
            )
        except socket.error as err:
            if err.errno == errno.EADDRINUSE:
                # print(' -> In Use')
                pass
            else:
                # print(' -> error({})'.format(err.errno))
                raise
        else:
            if self.__events[EventTypes.JOINED_GROUP]:
                self.__events[EventTypes.JOINED_GROUP](self, ip)

    def __doDropMembership(self, ip):
        try:
            mreq = struct.pack('4sL', socket.inet_aton(ip), socket.INADDR_ANY)
            self.__socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_DROP_MEMBERSHIP, mreq
            )
        except socket.error as err:
            if err.errno == errno.EADDRNOTAVAIL:
                # print(' -> Not In Use')
                pass
            else:
                # print(' -> error({})'.format(err.errno))
                raise
