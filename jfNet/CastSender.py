#! /usr/bin/env python3
# # -*- coding: UTF-8 -*-

import struct, socket
from typing import Optional
from . import EventTypes, SocketError


class CastSender:
    """建立一個發送 Multicast 多播的連線類別
    傳入參數:
        `evts` `dict{str:def,...}` -- 回呼事件定義，預設為 `None`
    """
    def __init__(self, ttl: int = 4):
        self.__events: dict = {
            EventTypes.SENDED: None,
            EventTypes.SENDFAIL: None
        }
        self.__socket: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.__socket.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, struct.pack('b', ttl))

    def bind(self, key:str, evt=None):
        """綁定回呼(callback)函式
        傳入參數:
            `key` `str` -- 回呼事件代碼；為避免錯誤，建議使用 *EventTypes* 列舉值
            `evt` `def` -- 回呼(callback)函式
        引發錯誤:
            `KeyError` -- 回呼事件代碼錯誤
            `TypeError` -- 型別錯誤，必須為可呼叫執行的函式
        """
        if key not in self.__events:
            raise KeyError(f'key:\'{key}\' not found!')
        if evt is not None and not callable(evt):
            raise TypeError(f'evt:\'{evt}\' is not a function!')
        self.__events[key] = evt

    def send(self, remote:tuple, data, waitback: bool = False) -> Optional[bytes]:
        """發送資料至多播位址
        傳入參數:
            `remote` `tuple(ip, port)` -- 多播位址
            `data` `str or bytearray` -- 欲傳送的資料
            `waitback` `bool` -- 是否等待遠端回覆資料，最長等待 1 秒
        引發錯誤:
            `jfSocket.SocketError` -- 多播位址不正確
            `Exception` -- 回呼的錯誤函式
        """
        v = socket.inet_aton(remote[0])[0]
        if isinstance(v, str):
            v = ord(v)
        if v not in range(224, 240):
            raise SocketError(1004)
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
            if waitback:
                sto = self.__socket.gettimeout()
                self.__socket.settimeout(1)
                try:
                    rec, addr = self.__socket.recvfrom(1024)
                except socket.timeout:
                    pass
                else:
                    if rec and len(rec) != 0:
                        return rec
                    else:
                        return None
                finally:
                    self.__socket.settimeout(sto)
