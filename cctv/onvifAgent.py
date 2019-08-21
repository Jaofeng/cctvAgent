#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import threading, types
from queue import Queue
from wsdiscovery import WSDiscovery, QName
from onvif import ONVIFCamera, ONVIFError
from urllib.parse import urlparse

ONVIF_TYPE_NVT = QName('http://www.onvif.org/ver10/network/wsdl', 'NetworkVideoTransmitter')
DEF_AUTHS = [('', ''), ('admin', ''), ('admin', 'admin')]

class OnvifAgent(object):
    def __init__(self, ipcams: list = None, log=None):
        '''CCTV 代理模組

        傳入:
            ipcams : dict -- IP Cam 資料清單, 每一項目應至少包含以下資料
                {'IP':str, 'Port':int, 'Profile':str, 'User':str, 'Passwd':str}
                IP      -- [必要]   IP Cam ONVIF 使用的 IP 位址
                Port    -- [非必要] IP Cam ONVIF 使用的通訊埠號, 預設值為 80
                Profile -- [必要]   使用的 Profile
                User    -- [非必要] 認證帳號
                Passwd  -- [非必要] 認證密碼
            log    : logging.Logger
        '''
        if ipcams:
            self.ipcams = list(ipcams)
        else:
            self.ipcams = []
        for ipc in self.ipcams:
            ipc['Port'] = ipc.get('Port', 80)
            ipc['SvcUrl'] = 'http://{}{}/onvif/device_service'.format(
                ipc["IP"], f':{ipc["Port"]}' if ipc['Port'] and ipc['Port'] != 80 else '')
        self.__started = False
        self.__seenSvcs = []
        self.__camInfo = []
        if log:
            self.log = log
        else:
            self.log = types.ModuleType('nolog')
            nolog = types.MethodType(lambda msg, *args, **kwargs: None, self.log)
            self.log.debug = self.log.info = nolog
            self.log.warn = self.log.warning = nolog
            self.log.error = self.log.exception = nolog

    def discovery(self, timeout=3):
        '''以 WS-Discovery 方式探索 IP Cam
        傳入:
            timeout : int -- 等待逾時時間, 單位秒, 預設 5 秒
        傳回:
            list(str) -- 搜尋到的 IP Cam 的 ONVIF 服務網址清單
        '''
        svcs = []
        try:
            wsd = WSDiscovery()
            wsd.start()
            services = wsd.searchServices(types=[ONVIF_TYPE_NVT], timeout=timeout)
        except Exception as ex:
            self.log.error(f'WS-Discovery Error:{ex}')
            return svcs
        else:
            for service in services:
                url = service.getXAddrs()[0]
                if not list(filter(lambda s: s == url, svcs)):
                    svcs.append(url)
            return svcs
        finally:
            wsd.stop()

    def getOnvifInfo(self, url, auths=None, queue: Queue = None):
        '''以 ONVIF 服務的網址、帳號與密碼, 取得 IP Cam 的 ONVIF 資料

        傳入:  
            url     : str           -- IP Cam ONVIF 服務的網址  
            auths   : list(tuple)   -- 以 (帳號,密碼) 為 Tuple 的 List 清單  
            queue   : Queue         -- 用以多執行緒時回傳取得的資料用
                                       當未傳入此值時, 將直接回傳(return)
                                       其回傳值型態如同傳回值
        傳回:
            dict -- ONVIF 資料, 格式如下:
            {
                'url':str, 'ip:str, 'port':int, 'hostName':str,
                'user':str, 'pwd':str,
                'source': {'name':str, 'resolution': {'width':int, 'height':int}}
                'profiles': [
                    {
                        'name':str, 'encoding':str,
                        'resolution': {'width':int, 'height':int},
                        'quality':int, 'frames':int, 'url':str,
                        'useit':bool
                    }
                ]
            }
        '''
        if not url: return None
        parsed = urlparse(url)
        if parsed.scheme != 'http':
            self.log.warn(f'"url"({url}) is not a ONVIF Service URL!')
            return None
        parts = parsed.netloc.split('@')[-1].split(':')
        ip = parts[0]
        port = parts[1] if len(parts) > 1 else 80
        authed = False
        self.log.debug(f'Get ONVIF information from \x1B[92m{url}\x1B[39m')
        res = {'url': url, 'ip': ip, 'port': port, 'hostName': ''}
        if not auths and not parsed.username:
            auths = DEF_AUTHS
        elif parsed.username:
            auths = [(parsed.username, parsed.password)]
        for authinfo in auths:
            if authed: break
            # Try get Camera Info
            try:
                mycam = ONVIFCamera(ip, port, authinfo[0], authinfo[1])
            except:
                continue
            # Get Host Name
            authed, hostName = self.__getHostName(mycam)
            if not authed: continue
            res['hostName'] = hostName
            res['user'] = authinfo[0]
            res['pwd'] = authinfo[1]
            # Get Profiles
            try:
                svc = mycam.create_media_service()
                profiles = svc.GetProfiles()
                vsc = svc.GetVideoSourceConfigurations()
                if vsc and len(vsc) != 0:
                    res['source'] = {
                        'name': vsc[0].Name,
                        'resolution': {'width': vsc[0].Bounds.width, 'height': vsc[0].Bounds.height}
                    }
            except:
                continue
            res['profiles'] = []
            for pf in profiles:
                vec = pf.VideoEncoderConfiguration
                rs = vec.Resolution
                d = {
                    'name': pf.Name,
                    'encoding': vec.Encoding,
                    'resolution': {'width': rs.Width, 'height': rs.Height},
                    'quality': vec.Quality,
                    'frames': vec.RateControl.FrameRateLimit,
                    'useit': False
                }
                try:
                    params = svc.create_type('GetStreamUri')
                    params.ProfileToken = pf.token
                    params.StreamSetup = {'Stream': 'RTP-Unicast', 'Transport': {'Protocol': 'RTSP'}}
                    resp = svc.GetStreamUri(params)
                    d['url'] = resp.Uri
                except:
                    pass
                res['profiles'].append(d)
        if authed:
            self.log.debug(res)
            if queue:
                queue.put(res)
            else:
                return res
        else:
            return None

    def renewIpCamInfo(self):
        '''以初始化傳入的清單為基準, 更新 IP Cam 的相關資料, 後續可由 `seenServices` 屬性值取得'''
        if not self.ipcams:
            return
        _queue = Queue()
        thds = []
        for ipc in self.ipcams:
            thd = threading.Thread(target=self.getOnvifInfo,
                                   args=(ipc['SvcUrl'],
                                         [(ipc.get('User', ''), ipc.get('Passwd', '')),],
                                         _queue))
            thd.setDaemon(True)
            thds.append(thd)
            thd.start()
        for thd in thds:
            thd.join(5)
        while not _queue.empty():
            rd = _queue.get()
            ipcs = [ipc for ipc in self.ipcams if ipc['IP'] == rd['ip'] and ipc['Port'] == rd['port']]
            rd['id'] = ipcs[0]['ID'] if ipcs else ''
            for pf in rd['profiles']:
                pf['useit'] = (pf['name'] == ipcs[0]['Profile'])
            lf = list(filter(lambda d: d['url'] == rd['url'], self.__seenSvcs))
            if not lf:
                self.__seenSvcs.append(rd)
                print(f'\x1B[93m[#]\x1B[39m Append service: \x1B[92m{rd["url"]}\x1B[39m')
            elif lf[0] != rd:
                self.__seenSvcs.remove(lf[0])
                print(f'\x1B[93m[#]\x1B[39m Remove service: \x1B[92m{lf[0]["url"]}\x1B[39m')
                self.__seenSvcs.append(rd)
                print(f'\x1B[93m[#]\x1B[39m Append service: \x1B[92m{rd["url"]}\x1B[39m')
            else:
                print(f'\x1B[93m[#]\x1B[39m Service exists: \x1B[92m{rd["url"]}\x1B[39m')

    def getOnvifInfoAfterDiscovery(self):
        '''以 WS-Discovery 搜尋 IP Cam 後, 一併取得其 IP Cam 的 ONVIF 相關資訊, 同時更新至 `seenServices` 屬性值中

        傳回:
            list(dict) -- 搜尋到的所有 IP Cam 的 ONVIF 資料, 格式如下:
            [
                {
                    'url':str, 'ip:str, 'port':int, 'hostName':str, 'id':str,
                    'user':str, 'pwd':str,
                    'source': {'name':str, 'resolution': {'width':int, 'height':int}}
                    'profiles': [
                        {
                            'name':str, 'encoding':str,
                            'resolution': {'width':int, 'height':int},
                            'quality':int, 'frames':int, 'url':str,
                            'useit':bool
                        }, ...
                    ]
                }, ...
            ]
        '''
        svcs = self.discovery()
        if not svcs: return None
        _queue = Queue()
        thds = []
        for url in svcs:
            thd = threading.Thread(target=self.getOnvifInfo, args=(url, DEF_AUTHS, _queue))
            thd.setDaemon(True)
            thd.start()
            thds.append(thd)
        for thd in thds:
            thd.join()
        res = []
        while not _queue.empty():
            rd = _queue.get()
            ipcs = [ipc for ipc in self.ipcams if ipc['SvcUrl'] == rd['url']]
            if ipcs:
                rd['id'] = ipcs[0]['ID']
                for pf in rd['profiles']:
                    pf['useit'] = (pf['name'] == ipcs[0]['Profile'])
            res.append(rd)
            lf = list(filter(lambda d: d['url'] == rd['url'], self.__seenSvcs))
            if not lf:
                self.__seenSvcs.append(rd)
            elif lf[0] != rd:
                self.__seenSvcs.remove(lf[0])
                self.__seenSvcs.append(rd)
        return res

    def __getHostName(self, mycam):
        # Host Name
        _auth = False
        _name = None
        try:
            resp = mycam.devicemgmt.GetHostname()
            if resp.Name:
                _name = str(resp.Name)
            _auth = True
        except ONVIFError as e:
            if 'not Authorized' in e.reason:
                _auth = False
        return _auth, _name

    isStarted = property(fget=lambda self: self.__started)

    @property
    def seenServices(self):
        '''傳回已取得 ONVIF 的資料清單

        傳回:
            list(dict) -- 資料清單內容, 資料格式為:
            [
                {
                    'url':str, 'ip:str, 'port':int, 'hostName':str, 'id':str,
                    'user':str, 'pwd':str,
                    'source': {'name':str, 'resolution': {'width':int, 'height':int}}
                    'profiles': [
                        {
                            'name':str, 'encoding':str,
                            'resolution': {'width':int, 'height':int},
                            'quality':int, 'frames':int, 'url':str,
                            'useit':bool
                        }, ...
                    ]
                }, ...
            ]
        '''
        return self.__seenSvcs
