#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import sys, os, socket, readline
from webSvc import HttpService, WebHandler, HttpEvents
from cctv.agent import CCTV_Agent as CCTV, AgentEvents
from cctv.rtspProxy import RtspProxy, HttpMJpegPusher

class Completer:
    def __init__(self, words):
        '''在 Console 下可使用類似 Hotkey 的方法'''
        self.words = words
        self.prefix = None

    def complete(self, prefix, index):
        if prefix != self.prefix:
            # we have a new prefix!
            # find all words that start with this prefix
            self.matching_words = [w for w in self.words if w.startswith(prefix)]
            self.prefix = prefix
        try:
            return self.matching_words[index]
        except IndexError:
            return None

# a set of more or less interesting words
COMMANDS = 'exit', 'help', 'host', 'cctv'
completer = Completer(COMMANDS)
readline.parse_and_bind('tab: complete')
readline.parse_and_bind('set editing-mode vi')
readline.set_completer(completer.complete)

_IpCams = [
    {"ID": "A-1", "IP": "172.18.0.74", "Profile": "OnvifProfile2", "User": "admin", "Passwd": ""}
]
_HttpPort = 8000
_ProxyPort = 8001
_LocalDomain = []
_Agent: CCTV = None
_Proxy: RtspProxy = None
_WebSvr: HttpService = None
_MJpeg: HttpMJpegPusher = None
_log = None

_help_commands_ = '''usage: command [argument]
commands and arguments:
  exit  : Exit this application
  help  : Print this help message
  cctv  : Show CCTV Information(if installed)
          > discovery : Discovery all IP Cams in same network, and get profiles
          > search    : Search IP Cams's ONVIF service ulr in same network
          > list      : Display all IP Cams information
          > clear     : Clear all discovered IP Cams
          > stream    : Display all IP Cams stream url
          > get       : Request ONVIF service information by ONVIF service Url
            >> url    : ONVIF service Url
            >> user   : User ID[opt], default ''
            >> passwd : Password[opt], default ''
            ext 1: cctv get http://192.168.0.10/onvif/device_service admin 1234
            ext 2: cctv get http://admin:1234@192.168.0.10/onvif/device_service
          > onvif     : Display all IP Cams ONVIF service url
          > info      : Display IP Cam detail information by ID
            >> id     : IP Cam's ID
          > proxy     : 
'''

def _setLogger():
    '''產生類似 logging.logger 變數'''
    global _log
    import types
    _log = types.ModuleType('console')
    # _log.debug = types.MethodType(lambda self, msg, *args, **kwargs: print(f'\x1B[90m{msg}\x1B[39m'), _log)
    _log.debug = types.MethodType(lambda self, msg, *args, **kwargs: None, _log)
    _log.info = types.MethodType(lambda self, msg, *args, **kwargs: print(msg), _log)
    _log.warn = _log.warning = types.MethodType(lambda self, msg, *args, **kwargs: print(f'\x1B[93m{msg}\x1B[39m'), _log)
    _log.error = _log.exception = types.MethodType(lambda self, msg, *args, **kwargs: print(f'\x1B[91m{msg}\x1B[39m'), _log)

def _entry():
    # 清除畫面
    if sys.platform.startswith('win'):
        _ = os.system("cls")    # windows
    else:
        _ = os.system("clear")  # linux
    print('\x1B[39;49m\x1B[3J')
    print('CCTV RTSP Streaming over HTTP v1.0.0')
    print(f'Run as Python \x1B[92mv{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}\x1B[39m')
    print('-' * 70)
    # Set Local Domain name
    global _LocalDomain, _IpCams, _Agent, _WebSvr, _Proxy
    _LocalDomain.append(socket.gethostname())
    _LocalDomain.append(socket.gethostbyname(socket.gethostname()))
    _setLogger()
    # Create CCTV Agent
    _Agent = CCTV(ipcams=_IpCams, log=_log)
    _Agent.bind(AgentEvents.FOUND, lambda ip, url: print(f'Found IP Cam(\x1b[92m{ip}\x1b[39m), Url:\x1b[92m{url}\x1b[39m'))
    _Agent.bind(AgentEvents.JOINED, _cctvJoined)
    _Agent.bind(AgentEvents.UPDATE, _cctvUpdate)
    _Agent.start()
    # Create HTTP Service
    WebHandler.remoteAccess = True
    if hasattr(WebHandler, 'events'):
        WebHandler.events[HttpEvents.GET] = _WebGET
    _WebSvr = HttpService(('', _HttpPort), 'www', WebHandler)
    _WebSvr.bind(HttpEvents.STARTED, lambda: _log.info(f'HTTP Server Starting @ Port: \x1B[92m{_WebSvr.port}\x1B[39m'))
    _WebSvr.bind(HttpEvents.STOPED, lambda: _log.warn(f'HTTP Server Stoped!'))
    _WebSvr.start()
    # Create RTSP Streaming Proxy over WebSocket
    _Proxy = RtspProxy(host=('', _ProxyPort), log=_log)
    _Proxy.start()
    # Console Wait Command Input
    _waitStdin()

def _waitStdin():
    cmd = ''
    while cmd != 'exit':
        try:
            cmd = input('> ')
            if len(cmd) == 0: continue
            cmds = cmd.split()
            code = cmds[0].lower()
            try:
                if code == 'exit':
                    _stopServer()
                elif code == 'help':
                    print(_help_commands_)
                elif code == 'host':
                    [print(f'{(i+1)}: {ip}') for i, ip in zip(range(0, len(_LocalDomain)), _LocalDomain)]
                elif code == 'cctv':
                    if len(cmds) < 2: continue
                    elif cmds[1] == 'discovery' and hasattr(_Agent, 'discoveryOnvif') and callable(_Agent.discoveryOnvif):
                        _Agent.discoveryOnvif(False)
                    elif cmds[1] == 'search' and hasattr(_Agent, 'discovery') and callable(_Agent.discovery):
                        #      0         1         2         3         4         5         6         7         8
                        #      012345678901234567890123456789012345678901234567890123456789012345678901234567890
                        urls = _Agent.discovery()
                        print('No. Host                  ONVIF Service Url')
                        from urllib.parse import urlparse
                        for no, url in zip(range(1, len(urls) + 1), urls):
                            parsed = urlparse(url)
                            print(f'{no:<3} {parsed.netloc:21} {url}')
                    elif cmds[1] == 'clear' and hasattr(_Agent, 'clear') and callable(_Agent.clear):
                        _Agent.clear()
                    elif cmds[1] == 'list' and hasattr(_Agent, 'ipcams'):
                        #      0         1         2         3         4         5         6         7         8         9
                        #      0123456789012345678901234567890123456789012345678901234567890123456789012345678901234567890
                        print('ID       Host              Name                 Profiles           Encoding Resolution  use')
                        for ipc in _Agent.ipcams:
                            host = ipc['ip'] + (':' + str(ipc['port']) if ipc['port'] != 80 else '')
                            print(f"{ipc['id']:<8} {host:<17} {(ipc['hostName'] if ipc['hostName'] else ''):<20} ", end='')
                            idx = 0
                            if ipc['profiles'] is None: continue
                            for pf in ipc['profiles']:
                                if idx != 0: print(' ' * 48, end='')
                                resol = f"{pf['resolution']['width']}x{pf['resolution']['height']}"
                                print(f"{pf['name']:<18} {pf['encoding']:<8} {resol:<12} ", end='')
                                print('*' if pf['useit'] else ' ')
                                idx += 1
                    elif cmds[1] == 'stream' and hasattr(_Agent, 'ipcams'):
                        #      0         1         2         3         4         5         6         7         8
                        #      012345678901234567890123456789012345678901234567890123456789012345678901234567890
                        print('ID       RTSP Streaming Url')
                        for ipc in _Agent.ipcams:
                            pfs = [pf for pf in ipc['profiles'] if pf['useit']]
                            if not pfs: continue
                            print(f"{ipc['id']:<8} {pfs[0]['url']}")
                    elif cmds[1] == 'onvif' and hasattr(_Agent, 'ipcams'):
                        #      0         1         2         3         4         5         6         7         8
                        #      012345678901234567890123456789012345678901234567890123456789012345678901234567890
                        print('ID       ONVIF Service Url')
                        for ipc in _Agent.ipcams:
                            print(f"{ipc['id']:<8} {ipc['url']}")
                    elif len(cmds) >= 3 and cmds[1] == 'get' and hasattr(_Agent, 'getOnvifInfo') and callable(_Agent.getOnvifInfo):
                        if len(cmds) >= 5:
                            auth = (cmds[3], cmds[4])
                        elif len(cmds) >= 4:
                            auth = (cmds[3], '')
                        else:
                            auth = ('', '')
                        print(f'Get ONVIF Information from')
                        print(f' > url: \x1B[92m{cmds[2]}\x1B[39m')
                        print(f' > username: \x1B[92m{auth[0]}\x1B[39m, passwd: \x1B[92m{auth[1]}\x1B[39m')
                        print(_Agent.getOnvifInfo(cmds[2], [auth]))
                    elif len(cmds) >= 3 and cmds[1] == 'info' and hasattr(_Agent, 'ipcams'):
                        ipcs = [ipc for ipc in _Agent.ipcams if ipc['id'] == cmds[2]]
                        if not ipcs:
                            print(f'\x1B[91mNot found IP Cam: \x1B[92m{cmds[2]}\x1B[39m')
                            continue
                        if len(cmds) >= 4 and cmds[3] == 'data':
                            print(ipcs[0])
                            continue
                        ipc = ipcs[0] 
                        pf = ipcs[0]
                        print(f"Basic Information:")
                        print(f"         ID : \x1B[92m{ipc['id']:<20}\x1B[39m", end='')
                        print(f"       Host : \x1B[92m{ipc['ip'] + (':' + str(ipc['port']) if ipc['port'] != 80 else '')}\x1B[39m")
                        hn = ipc['hostName'] if ipc['hostName'] else ''
                        print(f"       Name : \x1B[92m{hn:<20}\x1B[39m", end='')
                        print(f"  ONVIF Url : \x1B[92m{ipc['url']}\x1B[39m")
                        print(f"    User ID : \x1B[92m{ipc['user']:<20}\x1B[39m", end='')
                        print(f"   Password : \x1B[92m{ipc['pwd']}\x1B[39m")
                        print(f"Camera Source Information:")
                        print(f"       Name : \x1B[92m{ipc['source']['name']:<20}\x1B[39m", end='')
                        print(f" Resolution : \x1B[92m{ipc['source']['resolution']['width']}\x1B[39m x \x1B[92m{ipc['source']['resolution']['height']}\x1B[39m")
                        print(f"Profile Information:")
                        for pf in ipc['profiles']:
                            print(f"       Name : ", end='')
                            print('[\x1B[91mv\x1B[39m]' if pf['useit'] else '[ ]', end='')
                            print(f" \x1B[92m{pf['name']}\x1B[39m ")
                            print(f"   Encoding : \x1B[92m{pf['encoding']:<20}\x1B[39m", end='')
                            print(f" Resolution : \x1B[92m{pf['resolution']['width']}\x1B[39m x \x1B[92m{pf['resolution']['height']}\x1B[39m")
                            print(f"    Quality : \x1B[92m{pf['quality']:<20}\x1B[39m", end='')
                            print(f" Frames/Sec : \x1B[92m{pf['frames']}\x1B[39m")
                            print(f" Stream Url : \x1B[92m{pf['url']}\x1B[39m")
                    elif len(cmds) >= 3 and cmds[1] == 'proxy':
                        if cmds[2] == 'reset':
                            _Proxy.stop()
                            _Proxy.start()
                else:
                    print('Unknow command!')
            except SystemExit:
                break
            except Exception:
                import traceback
                _log.error(traceback.format_exc())
        except KeyboardInterrupt:
            break
    print('\x1B[39;49m')

def _stopServer():
    _Agent.stop()
    _WebSvr.stop()
    _Proxy.stop()
    raise SystemExit()

def _cctvJoined(info):
    print(f'\x1B[92m[*]\x1B[39m CCTV Joined...')
    print(info)

def _cctvUpdate(ip, info):
    print(f'\x1B[92m[*]\x1B[39m CCTV Information Updated...')
    print(f'    IP Addr: \x1B[92m{ip}\x1B[39m')
    print(f'    Update : \x1B[92m{info}\x1B[39m')

def _rtspUrls():
    '''取得所有 IP Cam 的 RTSP 的網址

    傳回:
        tuple(id:str, url:str)
    '''
    for ipc in _Agent.ipcams:
        pfs = [pf for pf in ipc['profiles'] if pf['useit']]
        if not pfs: continue
        yield (ipc['id'], pfs[0]['url'])

def _WebGET(handler, cnt):
    if not CCTV: return
    ri = cnt['info']
    fds = ri.url.split('/')
    if len(fds) < 2 or fds[0].lower() != 'live':
        return
    urls = [url for id, url in _rtspUrls() if id.lower() == fds[1].lower()]
    if not urls:
        handler.send_error((404, 'Not Found', 'Nothing matches the given URI'), f'Not found ID:{fds[1]}')
    try:
        resolution = tuple([int(x) for x in ri.query['size'][0].split('x')]) if ri.query and 'size' in ri.query else(0, 0)
    except:
        resolution = (0, 0)
    try:
        quality = int(ri.query['q'][0]) if ri.query and 'q' in ri.query else 0
    except:
        quality = 0
    cnt['handled'] = True
    print(f'url: {ri.url}, reslution: {resolution}, quality: {quality}')
    pxy = HttpMJpegPusher(handler, urls[0], resolution, quality)
    pxy.start()



if __name__ == '__main__':
    try:
        _entry()
    except Exception as ex:
        print(f'\x1B[91m{ex}\x1B[39m')
    finally:
        sys.exit(0)
