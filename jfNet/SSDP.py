#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import time, re
from logging import ERROR, WARN, INFO
from enum import Enum
from threading import Thread, Lock, Event
from . import EventTypes
from .CastReceiver import CastReceiver
from .CastSender import CastSender

SSDP_TTL = 4
SSDP_PORT = 1900
SSDP_MULITCAST_IP = '239.255.255.250'
SEARCH_RULE = re.compile(r'^M-SEARCH \* HTTP\/1\.1[.\n]*(?i)HOST:\W?239\.255\.255\.250:1900', flags=re.RegexFlag.IGNORECASE)
NOTIFY_RULE = re.compile(r'^NOTIFY \* HTTP\/1\.1[.\n]*(?i)HOST:\W?239\.255\.255\.250:1900')
MAC_RULE = re.compile(r'([0-9a-fA-F]{2}:){5}([0-9a-fA-F]{2})')
MAX_AGE = re.compile(r'max-age\W?=\W?(\d{1,})')

__all__ = ['SsdpEvents', 'SsdpInfo', 'SsdpContent', 'SsdpService']


class SsdpEvents(Enum):
    RECEIVED_SEARCH = 'onGetSSDPSearch'
    RECEIVED_NOTIFY = 'onGetSSDPNotify'
    RECEIVED_BYEBYE = 'onGetSSDPByebye'
    SENDED_SEARCH = 'onSendSSDPSearch'
    SENDED_NOTIFY = 'onSendSSDPNotify'
    DEVICE_JOINED = 'onDeviceJoined'
    DEVICE_LEAVED = 'onDeviceLeaved'
    LOGGING = 'onLogging'


class SsdpInfo(dict):
    __slots__ = []

    def __init__(self, **fields):
        for k, v in fields.items():
            self[k] = v
            self.__slots__.append(k)

    def __getattr__(self, attr):
        if attr in self:
            return self[attr]
        else:
            raise AttributeError

    def __setattr__(self, attr, val):
        if attr in self:
            self[attr] = val
        else:
            raise AttributeError

    def getFieldValue(self, attr):
        if attr in self:
            return self[attr]
        else:
            return None

    def clone(self):
        return SsdpInfo(**self)


class SsdpContent(SsdpInfo):
    def __init__(self, request_text):
        fields = {'method':''}
        lines = str.splitlines(request_text)
        m = re.search(r'(.*)\W\*\WHTTP\/(\d\.\d)', request_text)
        reg = re.compile(r'([\w-]*):\W?(.*)')
        if m:
            fields['method'] = m.group(1)
            for line in lines:
                if len(line) == 0: continue
                m = reg.search(line)
                if not m: continue
                fields[m.group(1).upper()] = m.group(2)
        super().__init__(**fields)


class SsdpService:
    def __init__(self):
        self.__rcv: CastReceiver = None
        self.__snd: CastSender = None
        self.__events: dict = {
            EventTypes.STARTED: None,
            EventTypes.STOPED: None,
            SsdpEvents.RECEIVED_SEARCH: None,
            SsdpEvents.RECEIVED_NOTIFY: None,
            SsdpEvents.RECEIVED_BYEBYE: None,
            SsdpEvents.SENDED_SEARCH: None,
            SsdpEvents.SENDED_NOTIFY: None,
            SsdpEvents.DEVICE_JOINED: None,
            SsdpEvents.DEVICE_LEAVED: None,
            EventTypes.LOGGING: None
        }
        self.__devices: list = []
        self.__st_rule = None
        self.__nt_rule = None
        self.__evt_stop_notify = Event()
        self.__evt_stop_search = Event()
        self.__evt_exit = Event()
        self.__listLocker = Lock()
        self.__createSender()

    def __del__(self):
        if not self.__evt_stop_notify.isSet:
            self.__evt_stop_notify.set()
            self.__evt_stop_notify = None
        if not self.__evt_stop_search.isSet:
            self.__evt_stop_search.set()
            self.__evt_stop_search = None
        if not self.__evt_exit.isSet:
            self.__evt_exit.set()
            self.__evt_exit = None
        self.__stopSender()
        self.__stopReceiver()
        self.__devices = None
        self.__events = None

    def __createReceiver(self, port, *ips):
        # args : Listen Port, Group Ip1, Group Ip2, ...
        self.__logMessage(INFO, f'Creating SSDP Listener @ Port: {port}')
        self.__rcv = CastReceiver(port)
        self.__rcv.bind(key=EventTypes.RECEIVED, evt=self.__dataReceived)
        self.__rcv.reusePort = True
        self.__rcv.reuseAddr = True
        self.__rcv.joinGroup(*ips)
        self.__rcv.recvBuffer = 1024
        self.__rcv.start()

    def __stopReceiver(self, *args):
        if self.__rcv and self.__rcv.isAlive:
            self.__logMessage(INFO, 'Stopping SSDP Listener...')
            self.__rcv.stop()
        self.__rcv = None

    def __createSender(self, *args):
        self.__logMessage(INFO, 'Creating SSDP Sender')
        self.__snd = CastSender(SSDP_TTL)
        self.__snd.bind(key=EventTypes.SENDED, evt=self.__dataSended)

    def __stopSender(self, *args):
        if self.__snd:
            self.__logMessage(INFO, 'Stopping Multicast Sender...')
            self.__snd = None

    def __dataReceived(self, *args):
        ipRemote, _ = args[3]
        dStr = str(args[1], 'iso-8859-1')
        cnt = SsdpContent(dStr)
        if cnt.method == 'M-SEARCH' and cnt.MAN == '"ssdp:discover"':
            self.__recSearch(ipRemote, cnt)
        elif cnt.method == 'NOTIFY' and cnt.NTS in ['ssdp:alive', 'ssdp:byebye']:
            self.__recNotify(ipRemote, cnt)

    def __dataSended(self, *args):
        ip, _ = args[2]
        dStr = args[1]
        if isinstance(dStr, bytearray) or isinstance(dStr, bytes):
            dStr = dStr.decode('utf-8')
        if SEARCH_RULE.match(dStr):
            evt = SsdpEvents.SENDED_SEARCH
        elif NOTIFY_RULE.match(dStr):
            evt = SsdpEvents.SENDED_NOTIFY
        if evt and self.__events[evt]:
            self.__events[evt](self, *args)

    def __recSearch(self, ip, cnt):
        if self.__st_rule:
            if (callable(self.__st_rule) and not self.__st_rule(cnt)) or\
                    (isinstance(self.__st_rule, re.Pattern) and not self.__st_rule.search(cnt.ST)):
                return
        if self.__events[SsdpEvents.RECEIVED_SEARCH]:
            self.__events[SsdpEvents.RECEIVED_SEARCH](self, cnt)

    def __recNotify(self, ip, cnt):
        if self.__nt_rule:
            if (callable(self.__nt_rule) and not self.__nt_rule(cnt)) or\
                    (isinstance(self.__nt_rule, re.Pattern) and not self.__nt_rule.search(cnt.USN)):
                return
        if cnt.NTS == 'ssdp:alive':
            m = MAX_AGE.search(cnt['CACHE-CONTROL'])
            if not m:
                self.__logMessage(WARN, 'Messing Content: max-age in Cache-Control!')
                return
            maxAge = int(m.group(1))
            isJoin = False
            with self.__listLocker:
                di = self.findDevices(ip=ip)
                if di and len(di) != 0:
                    di = di[0]
                    di.lastTime = time.time()
                else:
                    di = SsdpInfo(
                        ip=ip, maxAge=maxAge, lastTime=time.time(),
                        content=cnt
                    )
                    self.__devices.append(di)
                    isJoin = True
            if self.__events[SsdpEvents.RECEIVED_NOTIFY]:
                self.__events[SsdpEvents.RECEIVED_NOTIFY](self, di)
            if isJoin:
                if self.__events[SsdpEvents.DEVICE_JOINED]:
                    self.__events[SsdpEvents.DEVICE_JOINED](self, di)
        elif cnt.NTS == 'ssdp:byebye':
            # NOTIFY - BYEBYE
            with self.__listLocker:
                di = self.findDevices(ip=ip)
                if di and len(di) != 0:
                    self.__devices.remove(di[0])
            if di and len(di) != 0:
                if self.__events[SsdpEvents.RECEIVED_BYEBYE]:
                    self.__events[SsdpEvents.RECEIVED_BYEBYE](self, di[0])
                if self.__events[SsdpEvents.DEVICE_LEAVED]:
                    self.__events[SsdpEvents.DEVICE_LEAVED](self, di[0])

    # Private Event Methods
    def __logMessage(self, lv, msg):
        if self.__events[EventTypes.LOGGING]:
            self.__events[EventTypes.LOGGING](self, lv, msg)

    # Public Methods
    def start_listen(self):
        self.__evt_exit.clear()
        self.__createReceiver(SSDP_PORT, [SSDP_MULITCAST_IP])
        if self.__events[EventTypes.STARTED]:
            self.__events[EventTypes.STARTED](self)

    def stop_listen(self):
        self.__evt_exit.set()
        self.__stopReceiver()
        if self.__events[EventTypes.STOPED]:
            self.__events[EventTypes.STOPED](self)

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

    def findDevices(self, **kwargs) -> SsdpInfo:
        for k in ['mac', 'ip', 'hostId']:
            if k in kwargs:
                v = kwargs.get(k)
                return [di for di in self.__devices if di.getFieldValue(k) == v]
        return None

    def createSearchContent(self, **kwargs):
        '''建立 M-SEARCH 用的 HTML 內容

        傳入:
            `kwargs` `dict` -- 需包含以下內容
                `MX` `int` -- 遠端設備收到此通知時，需在此時間內回應，否則不於處理, 單位秒
                `ST` `str` -- 搜尋的目標識別字串
        '''
        if 'MX' not in kwargs or 'ST' not in kwargs:
            raise KeyError
        msg = 'M-SEARCH * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nMAN: "ssdp:discover"\r\n'
        for k in kwargs:
            if k.upper() == 'MAN' or k.upper() == 'HOST': continue
            msg += f'{k}: {kwargs.get(k)}\r\n'
        msg += '\r\n'
        return msg

    def search_forever(self, cycle, content):
        self.__evt_stop_search.clear()
        while not self.__evt_stop_search.wait(timeout=cycle):
            self.__snd.send((SSDP_MULITCAST_IP, SSDP_PORT), content)

    def search_once(self, content):
        self.__snd.send((SSDP_MULITCAST_IP, SSDP_PORT), content)

    def stop_search(self):
        self.__evt_stop_search.set()

    def setSearchFilter(self, rule):
        '''設定 M-SEARCH 用的設備過濾函式

        傳入:
            `rule` `str` -- 過濾條件, 以 ST 的內容作為過濾內容. 可傳入 Regular Expression 字串
            `rule` `callable` -- 過濾用函式, 呼叫此函式時, 將會傳入 SSDP 的 HTML Hdader(SSDP_Content) 內容
        '''
        if callable(rule):
            self.__st_rule = rule
        elif isinstance(rule, str):
            self.__st_rule = re.compile(rule)
        else:
            raise TypeError

    def createNotifyContent(self, **kwargs):
        '''建立 NOTIFY 用的 HTML 內容

        傳入:
            `kwargs` `dict` -- 需包含以下內容
                `max-age` `int` -- 本端發送 NOTIFY 的逾時認定時間, 單位秒. 建議使用 3 倍以上發送週期
                `LOCATION` `str` -- 本端設備的軟硬體資訊取得的網址或位置
                `NT` `str` -- 欲通知的遠端控制器的識別字串
                `USN` `str` -- 本端設備的軟硬體識別字串
        '''
        ks = ['max-age', 'LOCATION', 'NT', 'USN']
        if len([k for k in ks if k in kwargs]) != len(ks):
            return
        msg = 'NOTIFY * HTTP/1.1\r\nHost: 239.255.255.250:1900\r\nNTS: ssdp:alive\r\n'
        v = kwargs.get('max-age')
        msg += f'CACHE-CONTROL: max-age={v}\r\n'
        for k in kwargs:
            if k == 'max-age' or k.upper() == 'MAN' or k.upper() == 'NTS': continue
            msg += f'{k}: {kwargs.get(k)}\r\n'
        msg += '\r\n'
        return msg

    def notify_forever(self, cycle, content):
        self.__evt_stop_notify.clear()
        while not self.__evt_stop_notify.wait(timeout=cycle):
            try:
                self.__snd.send((SSDP_MULITCAST_IP, SSDP_PORT), content)
            except Exception as ex:
                self.__logMessage(ERROR, ex.msg)

    def notify_once(self, content):
        try:
            self.__snd.send((SSDP_MULITCAST_IP, SSDP_PORT), content)
        except Exception as ex:
            self.__logMessage(ERROR, ex.msg)

    def stop_notify(self):
        self.__evt_stop_notify.set()

    def setNotifyFilter(self, rule):
        '''設定 NOTIFY 用的設備過濾函式

        傳入:
            `rule` `str` -- 過濾條件, 以 USN 的內容作為過濾內容. 可傳入 Regular Expression 字串
            `rule` `callable` -- 過濾用函式, 呼叫此函式時, 將會傳入 SSDP 的 HTML Hdader(SSDP_Content) 內容
        '''
        if callable(rule):
            self.__nt_rule = rule
        elif isinstance(rule, str):
            self.__nt_rule = re.compile(rule)
        else:
            raise TypeError

    def clearDevices(self):
        if not self.__devices or len(self.__devices) == 0:
            return
        d = self.__devices.pop()
        while d:
            del d
            if len(self.__devices) == 0:
                break
            d = self.__devices.pop()
