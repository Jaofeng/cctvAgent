#! /usr/bin/env python3
# # -*- coding: UTF-8 -*-

import os, logging, threading, time, errno, json, cgi, re
from enum import Enum
from mimetypes import MimeTypes
from collections import namedtuple
from urllib.request import pathname2url
from http import HTTPStatus
from urllib import request
from urllib.parse import urlparse, parse_qs, unquote
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

__all__ = ['getMimeType', 'WebHandler']

RequestInfo = namedtuple('RequestInfo',
                         ['ip', 'url', 'query', 'path', 'file', 'isFolder',
                          'ctype', 'content', 'userAgent', 'isLocal'])
vreg = re.compile(r'<%(.*)%>')


def getMimeType(filename):
    '''傳回檔案的 MIMETYPE

    傳入:
        `filename` `str` -- 欲取得 MIMETYPE 的檔案名稱
    '''
    mime = MimeTypes()
    url = pathname2url(filename)
    mime_type = mime.guess_type(url)
    return mime_type[0]


class HttpEvents(Enum):
    STARTED = 'onStarted'
    STOPED = 'onStoped'
    GET = 'onGet'
    POST = 'onPort'


class HttpService:
    logger = logging.getLogger(__name__)
    server_version = 'HttpService/1.0'

    def __init__(self, host: tuple, root: str, handler: BaseHTTPRequestHandler):
        '''建立網頁伺服器 Web Server'''
        self.__evts = {
            HttpEvents.STARTED: None,
            HttpEvents.STOPED: None,
        }
        self.__evt_exit = threading.Event()
        self.handler = handler
        self.handler.webRoot = root
        self.handler.logger = self.logger
        self.handler.server_version = self.server_version
        self.host = host
        self.__svr = ThreadingHTTPServer(self.host, self.handler)
        self.__svr.timeout = 0.5
        self.__thd = threading.Thread(target=self.__httpWeb_Proc, daemon=True, args=(self.__svr, ))

    port = property(fget=lambda self: self.__svr.server_port, doc='服務監聽的通訊埠號')
    started = property(fget=lambda self: self.__thd.isAlive(), doc='是否執行中')

    # Thread Methods
    def __httpWeb_Proc(self, svr):
        '''執行 HTTP Web 等待連線的程序'''
        while not self.__evt_exit.wait(0.05):
            try:
                svr.handle_request()
            except Exception:
                pass
        if self.__evts[HttpEvents.STOPED]:
            self.__evts[HttpEvents.STOPED]()

    def __fakeLink(self):
        '''建立一個假連線(HEAD Request)，用以強制 HTTPServer 跳離 handle_request() 阻塞'''
        if self.__svr is None: return
        try:
            url = f'http://{self.__svr.server_name}:{self.__svr.server_port}/fake.link'
            req = request.Request(url)
            req.get_method = lambda: 'HEAD'
            request.urlopen(req)
        except Exception:
            pass

    def start(self):
        self.__evt_exit.clear()
        self.__thd.start()
        while not self.__thd.isAlive():
            time.sleep(0.1)
        if self.__evts[HttpEvents.STARTED]:
            self.__evts[HttpEvents.STARTED]()

    def stop(self):
        self.__evt_exit.set()
        self.__fakeLink()
        self.__thd.join()
        time.sleep(0.1)
        self.__svr.server_close()

    def bind(self, evt, callback):
        '''綁定回呼(callback)函式
        傳入參數:
            `evt` `str` -- 回呼事件代碼；為避免錯誤，建議使用 *WorkerEvents* 列舉值
            `callback` `def` -- 回呼(callback)函式
        引發錯誤:
            `KeyError` -- 回呼事件代碼錯誤
            `TypeError` -- 型別錯誤，必須為可呼叫執行的函式
        '''
        if evt not in self.__evts:
            raise KeyError(f'Event Key(evt):"{evt}" not found!')
        if callback is not None and not callable(callback):
            raise TypeError('"callback" not define or not a function!')
        self.__evts[evt] = callback


class WebHandler(BaseHTTPRequestHandler):
    DEFAULT_ERROR_MESSAGE = """
        <!DOCTYPE html>
        <html lang="zh-Hant" xmlns="http://www.w3.org/1999/xhtml">
            <head>
                <title>Error Response</title>
                <meta http-equiv="Content-Type" content="text/html;charset=utf-8">
            </head>
            <body style="color: white; background-color:black; padding-left: 20px; font-size:20px;">
                <h1>發生錯誤!</h1>
                <p>錯誤代碼: %(code)d</p>
                <p>錯誤訊息: %(message)s.</p>
                <p>%(code)s - %(explain)s.</p>
            </body>
        </html>
        """
    error_message_format = DEFAULT_ERROR_MESSAGE
    server_version = 'HttpService/1.0'
    protocol_version = 'HTTP/1.1'
    events = {
        HttpEvents.GET: None,
        HttpEvents.POST: None,
    }
    webRoot: str = os.getcwd()
    remoteAccess = False
    localhost = ['localhost', '127.0.0.1']
    logger = logging.getLogger(__name__)
    deviceKeys = []
    dynamicVars = None

    # Orerride Methods
    def do_GET(self):
        """
        Override Method HTTP GET
        """
        try:
            ri = self._getRequestInfo()
            if not ri:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if self.events[HttpEvents.GET]:
                cnt = {'info': ri, 'handled': False}
                self.events[HttpEvents.GET](self, cnt)
                if cnt['handled']: return
            if ri.isFolder:
                # 目錄型 API => http://domain/folder or http://domain/folder?abc=123
                self._GET_folder(ri)
            else:
                if len(ri.query) == 0:
                    fn = os.path.join(self.webRoot, ri.path, ri.file)
                    if not os.path.exists(fn):
                        self.send_error(HTTPStatus.NOT_FOUND, f'File Not Found: {self.path}')
                        return
                    mime = getMimeType(fn)
                    if mime.split('/')[-1] in ['html', 'javascript']:
                        self._responseDymanicPage(ri)
                    else:
                        self._responseFile(fn)
                else:
                    self._GET_file(ri)
        except IOError as ex:
            if ex.errno == errno.EPIPE:
                # 遠端已斷線
                pass
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
        except ConnectionResetError:
            pass
        except:
            self.logger.exception(f'do_GET Error!')
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        """
        Override Method HTTP POST
        """
        try:
            ri = self._getRequestInfo()
            if not ri:
                self.send_error(HTTPStatus.BAD_REQUEST)
                return
            if self.events[HttpEvents.POST]:
                cnt = {'info': ri, 'handled': False}
                self.events[HttpEvents.POST](self, cnt)
                if cnt['handled']: return
            if ri.isFolder:
                self._POST_folder(ri)
            else:
                self._POST_file(ri)
        except IOError as ex:
            if ex.errno == errno.EPIPE:
                # 遠端已斷線
                pass
            else:
                self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)
        except ConnectionResetError:
            pass
        except:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_HEAD(self):
        """
        Override Method HTTP HEAD
        """
        if self.path.lower().endswith('fake.link'):
            self.send_response(HTTPStatus.OK)
            return
        else:
            self.send_error(HTTPStatus.METHOD_NOT_ALLOWED)
            return

    def log_message(self, format, *args):
        """Override Method : Remove Console Messages"""
        pass
        # sys.stderr.write("%s - - [%s] %s\n" % (self.client_address[0], self.log_date_time_string(), format % args))

    def version_string(self):
        """Override Method : Return the server software version string."""
        return self.server_version

    def _getRequestInfo(self):
        '''取得 HTTP Request 內容
        傳回 :
            namedtuple('RequestInfo') -- 請求內容, 格式如下:
                {
                    'ip':str, 'url':str, 'path':str, 'file':str, 'isFolder':bool,
                    'ctype':str, 'content':dict, 'userAgent':str, 'isLocal':bool
                }
        '''
        log = f'{self.client_address[0]}:{self.client_address[1]} - {self.request_version} {self.command}'
        userAgent = self.headers.get('User-Agent')
        isLocal = self.headers.get('Host').split(':')[0].lower() in self.localhost
        url = 'index.html' if self.path in ['', '/'] else self.path.strip('/')
        info = urlparse(unquote(url))
        log += f' - {info.path}'
        qs = parse_qs(info.query)
        content = {}
        ctype = self.headers.get('content-type')
        if not ctype:
            ctype, pdict = '', {}
        else:
            ctype, pdict = cgi.parse_header(ctype)
        log += f' - {ctype}' if ctype else ''
        if ctype == 'multipart/form-data':
            content = cgi.parse_multipart(self.rfile, pdict)
        elif ctype in ['application/x-www-form-urlencoded', 'application/json', 'application/soap+xml']:
            length = int(self.headers.get('content-length', 0))
            if length:
                ctx = self.rfile.read(length).decode('utf-8')
                if ctype == 'application/json':
                    content = json.loads(ctx)
                elif ctype == 'application/soap+xml':
                    content = ctx
                else:
                    content = cgi.parse_qs(ctx, keep_blank_values=1)
        log += f' - {content}' if len(content) != 0 else ''
        self.logger.debug(log)
        return RequestInfo(
            ip=self.client_address[0],
            url=info.path.strip('/'),
            query=qs,
            path=os.path.dirname(info.path),
            file=os.path.basename(info.path),
            isFolder=(len(os.path.splitext(info.path)[1]) == 0),
            ctype=ctype,
            content=content,
            userAgent=userAgent,
            isLocal=isLocal)

    def _responseContent(self, mime, content):
        sc = content.encode('utf-8')
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-type', f'{mime}; charset=utf-8')
        self.send_header('Content-Length', len(sc))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(sc)

    def _responseFile(self, file):
        try:
            # 取得檔案 => http://domain/file.ext
            with open(file, 'rb', 4096) as f:
                fs = os.fstat(f.fileno())
                self.send_response(HTTPStatus.OK)
                self.send_header('Content-type', getMimeType(file))
                self.send_header('Content-Length', str(fs[6]))
                self.send_header('Last-Modified', self.date_time_string(fs.st_mtime))
                self.end_headers()
                buf = f.read()
                while buf:
                    self.wfile.write(buf)
                    buf = f.read()
                f.close()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND, f'File Not Found: {self.path}')
        except Exception as ex:
            self.logger.error(ex)
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, ex)

    def _responseDymanicPage(self, ri):
        fn = os.path.join(self.webRoot, ri.path, ri.file)
        if not os.path.exists(fn):
            self.send_error(HTTPStatus.NOT_FOUND, f'File Not Found: {self.path}')
            return
        with open(fn, 'r') as fs:
            cnt = fs.read()
            st = os.fstat(fs.fileno())
        m = vreg.search(cnt)
        while m:
            if self.dynamicVars and isinstance(self.dynamicVars, dict):
                if m.group(1) in self.shareData:
                    mp = self.shareData[m.group(1)]
                    rv = mp() if callable(mp) else mp
                else:
                    rv = ''
                    self.logger.warn(f'Unknow dynamic variable: {m.group(1)}')
            elif self.dynamicVars and callable(self.dynamicVars):
                rv = self.dynamicVars(m.group(1))
            else:
                rv = ''
                self.logger.warn(f'Can\'t replace dynamic variable: {m.group(1)}')
            cnt = cnt[:m.span()[0]] + str(rv) + cnt[m.span()[1]:]
            m = vreg.search(cnt)
        res = cnt.encode('utf-8')
        self.send_response(HTTPStatus.OK)
        self.send_header('Content-type', getMimeType(fn))
        self.send_header('Content-Length', len(res))
        # self.send_header('Cache-Control', 'no-cache')
        self.send_header('Last-Modified', self.date_time_string(st.st_mtime))
        self.end_headers()
        self.wfile.write(res)

    def _GET_folder(self, ri):
        """目錄型 GET API 用函式\n
        如：http://domain/folder or http://domain/folder?abc=123\n
        傳入:
            ri : RequestInfo -- Request Info
        """
        self.send_error(HTTPStatus.BAD_REQUEST)

    def _GET_file(self, info):
        """檔案型 GET API 用函式\n
        如：http://domain/file.ext?abc=123\n
        傳入:
            ri : RequestInfo -- Request Info
        """
        self.send_error(HTTPStatus.BAD_REQUEST)

    def _POST_folder(self, ri):
        """目錄型 POST API 用函式\n
        如：http://domain/folder or http://domain/folder?abc=123\n
        傳入:
            ri : RequestInfo -- Request Info
        """
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        template = f'<html><body>Folder POST OK<br>{ri.content}</body></html>'
        self.wfile.write(template.encode('utf-8'))

    def _POST_file(self, ri):
        """檔案型 GET API 用函式\n
        如：http://domain/file.ext?abc=123\n
        傳入:
            ri : RequestInfo -- Request Info
        """
        self.send_response(HTTPStatus.OK)
        self.end_headers()
        template = f'<html><body>File POST OK<br>{ri.content}</body></html>'
        self.wfile.write(template.encode('utf-8'))
