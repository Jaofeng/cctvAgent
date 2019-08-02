#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

# Ref.: https://www.itread01.com/content/1547446926.html

import threading, time, cv2, base64, types, json, re
from websocket_server import WebsocketServer, WebSocketHandler
from socketserver import TCPServer


__all__ = ['RtspProxy', 'HttpMJpegPusher']


def _parse_headers(had):
    reg = re.compile(r'(\S*):\s?([^\r]*)\r?')
    return dict(reg.findall(had))


class _wsServer(WebsocketServer):
    def __init__(self, port, host='127.0.0.1'):
        self.port = port
        TCPServer.__init__(self, (host, port), _wsHandler)


class _wsHandler(WebSocketHandler):
    def setup(self):
        '''覆寫自 websocket_server.WebSocketHandler.setup

        增加 path 與 headers 兩屬性
        '''
        super(_wsHandler, self).setup()
        self.path = ''
        self.headers = {}

    def handshake(self):
        '''覆寫自 websocket_server.WebSocketHandler.handshake

        增加 path 與 headers 兩屬性
        '''
        message = self.request.recv(1024).decode().strip()
        hd = re.search(r'GET (.*) HTTP/\d\.\d', message)
        if not hd:
            self.keep_alive = False
            return
        self.path = hd.group(1)
        self.headers = _parse_headers(message)
        upgrade = re.search('\nupgrade[\s]*:[\s]*websocket', message.lower())
        if not upgrade:
            self.keep_alive = False
            return
        key = re.search('\n[sS]ec-[wW]eb[sS]ocket-[kK]ey[\s]*:[\s]*(.*)\r\n', message)
        if key:
            key = key.group(1)
        else:
            print("Client tried to connect but was missing a key")
            self.keep_alive = False
            return
        response = self.make_handshake_response(key)
        self.handshake_done = self.request.send(response.encode())
        self.valid_client = True
        self.server._new_client_(self)


class _Camera(threading.Thread):
    '''自訂 Camera 執行緒類別, 此類別僅供 RtspProxy 使用'''
    def __init__(self, svr, url):
        super(_Camera, self).__init__()
        self.daemon = True
        self.__evt_exit = threading.Event()
        self.__svr = svr
        self.__lock = threading.Lock()
        self.url = url
        self.clients = []
        self.camera = cv2.VideoCapture(url)
        if not self.camera.isOpened():
            self.camera.open()
        self.resolution = (
            int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        )
        self.fps = int(self.camera.get(cv2.CAP_PROP_FPS))

    def __del__(self):
        self.clients = []
        if self.camera and self.camera.isOpened():
            self.camera.release()

    def run(self):
        self.__evt_exit.clear()
        while not self.__evt_exit.wait(timeout=0.05):
            ret, frame = self.camera.read()
            if ret:
                thds = []
                for clt in self.clients:
                    if self.__evt_exit.isSet(): break
                    pkgs = self.__encodingImage(frame, clt['resolution'])
                    if not pkgs: continue
                    thd = threading.Thread(target=self.__sendPackages, daemon=True, args=(clt, pkgs))
                    thds.append(thd)
                [thd.start() for thd in thds]
                [thd.join() for thd in thds]
            else:
                # 讀取失敗，重置 IP Cam
                if self.__evt_exit.isSet(): break
                self.camera = cv2.VideoCapture(self.url)
                if not self.camera.isOpened(): self.camera.open()

    def stop(self):
        self.__evt_exit.set()
        time.sleep(0.1)
        if self.camera and self.camera.isOpened():
            self.camera.release()

    def appendClient(self, client):
        with self.__lock:
            ids = [c for c in self.clients if c['id'] == client['id']]
            if not ids:
                self.clients.append(client)
            else:
                ids[0].update(client)

    def removeClient(self, client):
        with self.__lock:
            [self.clients.remove(c) for c in self.clients if c['id'] == client['id']]

    def updateClient(self, client):
        with self.__lock:
            [c.update(client) for c in self.clients if c['id'] == client['id']]

    def __find(self, id):
        ids = [c for c in self.clients if c['id'] == id]
        return ids[0] if ids else None

    def __encodingImage(self, frame, resolution=(0, 0), quality=0, size=32 * 1024):
        '''將圖片依 resolution 調整解析度, 並編碼成可傳輸之 base64 字串
        傳入:
            frame     : cv2 image - 來自 OpenCV 的圖像(頁框)資料
            resolution: tuple - 欲調整的解析度, 格式為 (width, height)
                                未傳入或傳入 (0, 0) 時則表示不調整, 預設值不調整
            quality   : int - 壓縮品質, 1~100, 預設值為 0 表示原畫質不壓縮
            size      : int - 拆解的封包大小
        傳回:
            list(str) - 拆解完成的字串列表
        '''
        frm = frame if resolution == (0, 0) or resolution == self.resolution else cv2.resize(frame, resolution)
        quality = 100 if quality > 100 else 0 if quality < 0 else quality
        if quality != 0:
            params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
            ret, image = cv2.imencode('.jpg', frm, params)
        else:
            ret, image = cv2.imencode('.jpg', frm)
        if not ret: return None
        base64_data = base64.b64encode(image)
        buf = f'data:image/jpeg;base64,{base64_data.decode()}'
        # 拆解封包內容
        pks = len(buf) / size
        pks = int(pks) + 1 if int(pks) != pks else int(pks)
        return [f'~{int(i/size)+1}~{buf[i:i + size]}' for i in range(0, len(buf), size)]

    def __sendPackages(self, client, pkgs):
        if not pkgs: return
        try:
            self.__svr.send_message(client, f"::{len(pkgs)}::")
            [self.__svr.send_message(client, pkg) for pkg in pkgs if not self.__evt_exit.isSet()]
        except:
            pass


class RtspProxy(object):
    def __init__(self, host, log=None):
        self.clients = []
        self.cameras = []
        # 建立 Websocket Server
        self.__svr = _wsServer(host=host[0], port=host[1])
        self.host = self.__svr.server_address
        # 有裝置連線上時呼叫
        self.__svr.set_fn_new_client(self.__newClient)
        # 斷開連線時呼叫
        self.__svr.set_fn_client_left(self.__clientLeft)
        # 接收到資訊
        self.__svr.set_fn_message_received(self.__msgReceived)
        if log:
            self.log = log
        else:
            self.log = types.ModuleType('nolog')
            nolog = types.MethodType(lambda msg, *args, **kwargs: None, self.log)
            self.log.debug = self.log.info = nolog
            self.log.warn = self.log.warning = nolog
            self.log.error = self.log.exception = nolog

    def __newClient(self, client, server):
        '''
        client is a dict:
            {
                'id'      : id,
                'handler' : handler,
                'address' : (addr, port)
            }
        '''
        self.log.debug(f"New client connected, ID: \x1B[92m{client['id']}\x1B[39m")
        self.clients.append(client)

    def __clientLeft(self, client, server):
        self.log.debug(f"Client(\x1B[92m{client['id']}\x1B[39m) disconnected")
        [cam.removeClient(client) for cam in self.cameras if cam.url == client['url']]
        [self.clients.remove(c) for c in self.clients if c['id'] == client['id']]

    def __msgReceived(self, client, server, message):
        self.log.debug(f"Client(\x1B[92m{client['id']}\x1B[39m) said: \x1B[92m{message}\x1B[39m")
        d = json.loads(message)
        clts = [c for c in self.clients if c['id'] == client['id']]
        if not clts: return
        act = d.get('act', None)
        if not act: return
        if act == 'open':
            url = d.get('url', None)
            if not url: return
            clts[0]['resolution'] = tuple(d.get('resolution', (0, 0)))
            ourl = clts[0].get('url', '')
            if ourl != url:
                [cam.removeClient(clts[0]) for cam in self.cameras if cam.url == ourl]
                clts[0]['url'] = url
                # 原先連線的網址為空值或與現在要連線的網址不同
                cams = [cam for cam in self.cameras if cam.url == url]
                if not cams:
                    cam = _Camera(self.__svr, url)
                    self.cameras.append(cam)
                    cam.start()
                else:
                    cam = cams[0]
                cam.appendClient(clts[0])
        elif act == 'resize':
            clts[0]['resolution'] = tuple(d.get('resolution', (0, 0)))
            [cam.updateClient(clts[0]) for cam in self.cameras if cam.url == clts[0]['url']]

    def start(self):
        threading.Thread(target=self.__svr.run_forever, daemon=True).start()
        ip = '*' if not self.host[0] or self.host[0] == '0.0.0.0' else self.host[0]
        self.log.info(f'RTSP WebSocket Proxy Started @ \x1B[92mws://{ip}:{self.host[1]}/\x1B[39m')

    def stop(self):
        for cam in self.cameras:
            for c in self.clients:
                cam.removeClient(c)
                self.clients.remove(c)
            cam.stop()
            cam.join(0.1)
            self.cameras.remove(cam)
        self.__svr.server_close()
        self.log.warn(f'RTSP WebSocket Proxy Stoped')


class HttpMJpegPusher(threading.Thread):
    BOUNDARY_KEY = '--jpgboundary'

    def __init__(self, handler, rtsp, size=(0, 0), quality=0):
        super(HttpMJpegPusher, self).__init__(daemon=True)
        self.size = size or (0, 0)
        self.quality = quality or 70
        self.daemon = True
        self.handler = handler
        self.rtsp = rtsp
        self.__evt_exit = threading.Event()
        self.camera = cv2.VideoCapture(rtsp)
        if not self.camera.isOpened():
            self.camera.open()
        self.resolution = (
            int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH)),
            int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        )
        self.fps = int(self.camera.get(cv2.CAP_PROP_FPS))

    def __del__(self):
        self.clients = []
        if self.camera and self.camera.isOpened():
            self.camera.release()

    def run(self):
        self.__evt_exit.clear()
        try:
            self.handler.send_response(200)
            self.handler.send_header('Content-type', f'multipart/x-mixed-replace;boundary={self.BOUNDARY_KEY}')
            self.handler.end_headers()
            time.sleep(0.2)
        except:
            return
        while not self.__evt_exit.wait(timeout=0.05):
            ret, frame = self.camera.read()
            if ret:
                frm = frame if (self.size == (0, 0) or self.size == self.resolution) else cv2.resize(frame, self.size)
                quality = 100 if self.quality > 100 else 0 if self.quality <= 0 else self.quality
                if quality == 0:
                    params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]
                    ret, jpg = cv2.imencode('.jpg', frm, params)
                else:
                    ret, jpg = cv2.imencode('.jpg', frm)
                try:
                    self.handler.wfile.write(f'{self.BOUNDARY_KEY}\r\n'.encode('latin-1', 'strict'))
                    self.handler.send_header('Content-type', 'image/jpeg')
                    self.handler.send_header('Content-length', str(jpg.size))
                    self.handler.end_headers()
                    self.handler.wfile.write(jpg.tostring())
                    self.handler.wfile.write(b'\r\n\r\n')
                    self.handler.wfile.flush()
                except (OSError, ConnectionResetError):
                    break
                except:
                    pass
            else:
                # 讀取失敗，重置 IP Cam
                if self.__evt_exit.isSet(): break
                self.camera = cv2.VideoCapture(self.url)
                if not self.camera.isOpened(): self.camera.open()

    def stop(self):
        self.__evt_exit.set()
        time.sleep(0.1)


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if not args:
        print('usage: python rtspProxy.py ip:port')
        sys.exit(0)
    proxy = RtspProxy(tuple(args[0].split(':')))
    proxy.start()
    ip = '*' if not proxy.host[0] or proxy.host[0] == '0.0.0.0' else proxy.host[0]
    print(f'RTSP WebSocket Proxy Started @ \x1B[92mws://{ip}:{proxy.host[1]}/\x1B[39m')
    cmd = ''
    while cmd != 'exit':
        try:
            cmd = input(': ')
            if len(cmd) == 0: continue
            cmds = cmd.split()
            if cmds[0].lower() == 'exit':
                proxy.stop()
                sys.exit(0)
            else:
                print('Unknow command! please use \'exit\' to exit...')
        except:
            pass
    print('\x1B[39;49m')
    sys.exit(0)
