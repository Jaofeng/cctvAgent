#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import time, re, types
from threading import Lock
from typing import Optional, List, Dict
from enum import Enum, unique
from urllib import request, error
from http.client import BadStatusLine
from jfNet import EventTypes
from jfNet.SSDP import SsdpService, SsdpEvents, SsdpInfo
from . import AttribDict, xml2Dict
from .onvifAgent import OnvifAgent

_epFilter = re.compile(r'(http://)?(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:?\d{0,5})\/?')


@unique
class CCTV_Events(Enum):
    """
    事件代碼列舉
    提供 `CCTV_Worker` 所有類別回呼用事件的鍵值
    """
    FOUND = 'found'
    JOINED = 'joined'
    UPDATE = 'undated'
    ONLINE = 'online'
    OFFLINE = 'offline'


class CCTV_Worker:
    def __init__(self, ipcams=None, log=None):
        self.__events: dict = {
            CCTV_Events.FOUND: None,
            CCTV_Events.JOINED: None,
            CCTV_Events.UPDATE: None,
            CCTV_Events.ONLINE: None,
            CCTV_Events.OFFLINE: None,
        }
        self.__ssdp = SsdpService()
        self.__ssdp.bind(EventTypes.STARTED,self.__Started)
        self.__ssdp.bind(EventTypes.STOPED, self.__Stoped)
        self.__ssdp.bind(SsdpEvents.DEVICE_JOINED, self.__onJoined)
        self.__ssdp.bind(SsdpEvents.RECEIVED_BYEBYE, self.__onLeaved)
        self.__ssdp.setNotifyFilter(r'upnp_NetworkCamera')
        self.__onvif: OnvifAgent = OnvifAgent(ipcams=ipcams, log=log)
        self.__devs: List[Dict] = []
        self.__locker: Lock = Lock()
        if log:
            self.log = log
        else:
            self.log = types.ModuleType('nolog')
            nolog = types.MethodType(lambda msg, *args, **kwargs: None, self.log)
            self.log.debug = self.log.info = nolog
            self.log.warn = self.log.warning = nolog
            self.log.error = self.log.exception = nolog

    ipcams = property(fget=lambda self: self.__devs)

    def __getitem__(self, **kwargs) -> Optional[str]:
        for k in ['ip', 'name']:
            if k in kwargs:
                v = kwargs.get(k)
                return [ipc for ipc in self.__devs if ipc[k] == v]
        return None

    def start(self, search: bool = False):
        self.__ssdp.start_listen()
        self.__onvif.renewIpCamInfo()
        self.__devs = self.__onvif.seenServices
        if search: self.discoveryOnvif()

    def stop(self):
        self.__ssdp.stop_listen()

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
            raise KeyError(f'key:"{key}" not found!')
        if evt is not None and not callable(evt):
            raise TypeError('"evt" is not a callable function!')
        self.__events[key] = evt

    def findDevices(self, **kwargs):
        for k in ['ip']:
            if k in kwargs:
                v = kwargs.get(k)
                return [d for d in self.__devs if d[k] and d[k] == v]
        return None

    def discovery(self):
        return self.__onvif.discovery()

    def discoveryOnvif(self, byProc=True):
        dl = self.__onvif.getOnvifInfoAfterDiscovery()
        if not dl:
            self.log.debug('Not found any IP Cam')
            if not byProc:
                print('Not found any IP Cam')
            return
        for dd in dl:
            if 'profiles' not in dd:
                continue
            d = AttribDict(**dd)
            fd = self.findDevices(ip=d.ip)
            if not fd or len(fd) == 0:
                if self.__events[CCTV_Events.FOUND]:
                    self.__events[CCTV_Events.FOUND](d.ip, d.url)
                self.__appedIpCam({
                    'ip': d.ip, 'svcUrl': d.url, 'name': d.hostName,
                    'profiles': d.profiles,
                    'joinTime': time.time(), 'lastTime': time.time(),
                    'Alive': True
                })
            else:
                fd = fd[0]
                fd['lastTime'] = time.time()
                fd['alive'] = True
                fd['name'] = d.hostName
                if not fd['profiles'] or not byProc:
                    fd['svcUrl'] = d.url
                    fd['profiles'] = d.profiles
                    self.log.debug(fd['profiles'])
                    if self.__events[CCTV_Events.UPDATE]:
                        self.__events[CCTV_Events.UPDATE](fd['ip'], fd['profiles'])

    def clear(self):
        self.__ssdp.clearDevices()
        with self.__locker:
            if not self.__devs or len(self.__devs) == 0:
                return
            d = self.__devs.pop()
            while d:
                del d
                if len(self.__devs) == 0:
                    break
                d = self.__devs.pop()

    def getOnvifInfo(self, url, auths=None):
        return self.__onvif.getOnvifInfo(url, auths=auths)

    def __Started(self, svc):
        self.log.info('CCTV Monitor Agent Started')

    def __Stoped(self, svc):
        self.__devs = []
        self.log.warn('CCTV Monitor Agent Stoped!')

    def __onJoined(self, svc, di):
        '''收到新設備發送 SSDP NOTIFY 時產生此事件
        傳入:
            `svc` `SSDPService` -- SSDPService
            `di` `SsdpInfo` -- SsdpInfo{ip:str, maxAge:int, lastTime:time, content=dict(SSDP Content)}
        '''
        self.log.debug(f'IP Cam @ \x1B[92m{di.ip}\x1B[39m(USN:\x1B[92m{di.content.USN}\x1B[39m) Joined')
        fd = self.findDevices(ip=di.ip)
        if not fd or len(fd) == 0:
            self.__appedIpCam(di)
        else:
            fd = fd[0]
            fd['alive'] = True
            fd['lastTime'] = time.time()
            if not fd['profiles']:
                url = fd['svcUrl']
                oi = self.__onvif.getOnvifInfo(url)
                if oi:
                    fd['profiles'] = oi['profiles']
                    fd['name'] = oi['hostName']
                if self.__events[CCTV_Events.UPDATE]:
                    self.__events[CCTV_Events.UPDATE](fd['ip'], fd['profiles'])

    def __onLeaved(self, svc, di):
        pass

    def __appedIpCam(self, di):
        if isinstance(di, SsdpInfo):
            domain = di.ip
            name = ''
            loc = di.content.LOCATION if di.content.LOCATION else None
            if loc:
                ok, dev = self.__getDevInfoFromSsdp(loc)
                if ok:
                    m = _epFilter.match(dev['presentationURL'])
                    if m:
                        domain = m.group(2)
                    name = dev.get('friendlyName', None)
                else:
                    self.log.warn(dev)
            ipc = {
                'ip': di.ip, 'maxAge': di.maxAge, 'joinTime': di.lastTime,
                'name': name, 'lastTime': di.lastTime,
                'svcUrl': f'http://{domain}/onvif/device_service',
                'profiles': None,
                'alive': True
            }
        elif isinstance(di, dict) or isinstance(di, AttribDict):
            ipc = di
        else:
            return
        if ('profiles' not in ipc or ipc['profiles'] is None) and ipc['svcUrl']:
            url = ipc['svcUrl']
            self.log.debug(f'Get ONVIF info from: {url}')
            oi = self.__onvif.getOnvifInfo(ipc['svcUrl'])
            if oi: ipc['profiles'] = oi['profiles']
        with self.__locker:
            if isinstance(ipc, dict):
                self.__devs.append(AttribDict(**ipc))
            else:
                self.__devs.append(ipc)
        if self.__events[CCTV_Events.JOINED]:
            self.__events[CCTV_Events.JOINED](ipc)

    def __getDevInfoFromSsdp(self, url: str):
        buf = None
        self.log.info(f'Get Device information from \x1B[93m{url}\x1B[39m')
        try:
            req = request.Request(url)
            with request.urlopen(req) as res:
                buf = res.read()
            xml = str(buf, 'iso-8859-1')
            d = xml2Dict(xml)
            return True, d['root']['device']
        except BadStatusLine as ex:
            return False, f'\x1B[91mBadStatusLine!\x1B[39m url:\x1B[93m{url}\x1B[39m - \x1B[91m{ex}\x1B[39m'
        except error.URLError as ex:
            return False, f'\x1B[91mURLError!\x1B[39m url:\x1B[93m{url}\x1B[39m - \x1B[91m{ex}\x1B[39m'
        except ConnectionResetError as ex:
            return False, f'\x1B[91mConnection Reset!\x1B[39m url:\x1B[93m{url}\x1B[39m - \x1B[91m{ex}\x1B[39m'
        except Exception as ex:
            return False, f'\x1B[91mException!\x1B[39m url:\x1B[93m{url}\x1B[39m - {type(ex)} - \x1B[91m{ex}\x1B[39m'
