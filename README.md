# RTSP Over HTTP Solution

## *前言*
因工作上的需要，需要將 IP Cam 即時影像顯示在終端設備上，作為監控螢幕使用。

一般的作法是直接利用 NVR 廠商提供的 SDK/Player 進行顯示播放，但廠商提供的 SDK/Player 是 Windows base 的，而終端設備卻是 Linux 且 GUI 為 Web base，不得不自行從 IP Cam 接取 RTSP 影像串流。

雖然網路上有很多資源可以幾乎不花心力就可以做到所需功能，但還是想研究一下何謂 SSPD、ONVIF、RTSP、Streaming 等等相關知識，所以才會有這個專案。

## *第三方模組*
* WebSocket 使用 [websocket_server](https://github.com/Pithikos/python-websocket-server)  
```pip install git+https://github.com/Pithikos/python-websocket-server```
* WS-Discovery 使用 [wsdiscovery](https://github.com/andreikop/python-ws-discovery)  
```pip install WSDiscovery```
* ONVIF 相關功能使用 [python-onvif](http://github.com/rambo/python-onvif)  
```pip install onvif-py3```
* RTSP 串流擷取使用 [OpenCV](https://github.com/skvark/opencv-python)  
```pip install opencv-python```

## *專案目錄結構*
    . 
    ├─ cctv
    │  ├─ __init__.py
    │  ├─ agent.py
    │  ├─ onvifAgent.py
    │  └─ rtspProxy.py
    ├─ jfNet
    │  ├─ __init__.py
    │  ├─ CastReceiver.py
    │  ├─ CastSender.py
    │  ├─ SSDP.py
    │  ├─ TcpClient.py
    │  └─ TcpServer.py
    ├─ www
    │  ├─ css
    │  │  ├─ base.css
    │  │  └─ index.css
    │  ├─ js
    │  │  ├─ index.js
    │  │  ├─ jquery.min.js
    │  │  ├─ rtspProxy.js
    │  │  ├─ rtspProxy.min.js
    │  │  └─ index.css
    │  └─ index.html
    ├─ cctvAgent.py
    └─ webSvc.py

### *檔案說明*
* cctv 目錄是本專案主要模組，其中包含：
  * agent.py  
    負責處理 IP Cam 探索，使用 UPnP/SSDP 與 WS-Discovery 兩種技術，如果不需要主動搜尋 IP Cam，可不使用此模組
  * onvifAgent.py  
    ONVIF 協定相關資料取得，譬如 IP Cam 的 Profile、串流網址、解析度、編碼模式等
  * rtspProxy.py  
    使用 OpenCV 讀取 RTSP 串流，再以 WebSocket 或 Motion JPEG(M-Jpeg) over HTTP 串流輸出
* www 是 HTML 網頁目錄
* cctvAgent.py  
  程式進入點，執行後可使用 help 檢視可使用的指令
* webSvc.py  
  繼承自 BaseHTTPRequestHandler 的 HTTP Web Server 模組
* jfNet 模組是本人另一專案, 請參閱 [jaofeng/SocketTest](https://github.com/Jaofeng/SocketTest)

## *原理說明*
> 原理其實很簡單：  
當終端要求取得影像時，使用 **OpenCV** 向 **RTSP** 來源拉流(讀取當下影像)，再推流至終端瀏覽器顯示


## *使用說明*
* WebSocket 傳輸時，為避免因傳輸的內容太大(Bytes to Base64，原始大小如 30KBytes，會擴張成 40KBytes)，造成 TCP Retry 過於頻繁，所以在傳給使用者前，會先把 Base64 以 32KBytes 為單位進行切割，到 JavaScript 後，再將之組合，最後指給 img.src 顯示
* IP Cam 的 IP 位址與 Profile ID，請於 cctvAgent.py 與 index.js 中設定，或請自行修改成讀取參數檔的方式載入
* 使用 WebSocket 傳輸串流時，需搭配 js 目錄中的 rtspProxy(.min).js 使用
* 如需將 WebSocket 串流方式提供給非本機連線，請自行將 index.js 內的 cctv.ProxyHost 修改成本機 IP
* rtspProxy(.min).js 與 M-Jpeg 的使用方式，請參閱 index.js 內的 useRtspProxy() 與 useHttpMJpegPuller() 兩函式
* 終端顯示順暢與否、是否會延遲，取決於原始 RTSP 串流解析度、網路品質、終端顯示解析度等等
* 經在同一封閉網路的不負責實測:satisfied:，對終端設備負載較輕的方式是 M-Jpeg
  * 測試環境設備：
    * Server : MacBook Pro 13" / Mojave 10.14.5
    * Client : tBOX810-838-FL / Debian 10, Kernel 14.2
  * 測試結果：
    * 以 CPU Usage 而言，WebSocket 高於 M-Jpeg 1.2 倍
    * 以記憶體用量而言，兩者差不多
    * 以網路流量而言，WebSocket 高於 M-Jpeg 1.4 倍


## *參考資料*
* 串流知識
  * HTML5 視頻直播（一）~（三）  
    https://imququ.com/post/html5-live-player-1.html
    https://imququ.com/post/html5-live-player-2.html
    https://imququ.com/post/html5-live-player-3.html
* WebSocket Streaming
  * 基于WebSocket的网页(JS)与服务器(Python)数据交互  
  https://zhaoxuhui.top/blog/2018/05/05/WebSocket&Client&Server.html
  * html通過websocket與python播放rtsp視訊  
  https://www.itread01.com/content/1547446926.html
* Motion JPEG over HTTP
  * [stack overflow] How to parse mjpeg http stream from ip camera?  
    https://stackoverflow.com/questions/21702477/how-to-parse-mjpeg-http-stream-from-ip-camera
  * C#开源实现MJPEG流传输  
    https://www.cnblogs.com/gaochundong/p/csharp_mjpeg_streaming.html
* OpenCV
  * OpenCV-Python Tutorials  
    https://opencv-python-tutroals.readthedocs.io/en/latest/py_tutorials/py_tutorials.html
  * Python 與 OpenCV 基本讀取、顯示與儲存圖片教學  
    https://blog.gtwang.org/programming/opencv-basic-image-read-and-write-tutorial/