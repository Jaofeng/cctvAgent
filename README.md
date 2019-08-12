# RTSP Over HTTP Solution

## *前言*
因工作上的需要，需要將 IP Cam 即時影像顯示在終端設備上，作為監控螢幕使用。

一般的作法是直接利用 NVR 廠商提供的 SDK/Player 進行顯示播放，但廠商提供的 SDK/Player 是 Windows base 的，而終端設備卻是 Linux 且 GUI 為 Web base，不得不自行從 IP Cam 接取 RTSP 影像串流。

雖然網路上有很多資源可以幾乎不花心力就可以做到所需功能，但還是想研究一下何謂 `SSPD`、`ONVIF`、`RTSP`、`Streaming` 等等相關知識，所以才會有這個專案。

本人非影像專業工程師，如有謬論或錯誤，懇請各位先進不吝告知

## *第三方模組*
* WebSocket 使用 [websocket_server](https://github.com/Pithikos/python-websocket-server)  
`pip install git+https://github.com/Pithikos/python-websocket-server`
* WS-Discovery 使用 [wsdiscovery](https://github.com/andreikop/python-ws-discovery)  
`pip install WSDiscovery`
* ONVIF 相關功能使用 [python-onvif](http://github.com/rambo/python-onvif)  
`pip install onvif-py3`
* RTSP 串流擷取使用 [OpenCV](https://github.com/skvark/opencv-python)  
`pip install opencv-python`

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
    負責處理 IP Cam 探索，使用 `UPnP/SSDP` 與 `WS-Discovery` 兩種技術，如果不需要主動搜尋 IP Cam，可不使用此模組
  * onvifAgent.py  
    `ONVIF` 協定相關資料取得，譬如 IP Cam 的 `Profile`、`串流網址`、`解析度`、`編碼模式`等
  * rtspProxy.py  
    使用 `OpenCV` 讀取 `RTSP` 串流，再以 `WebSocket` 或 `Motion JPEG(M-Jpeg) over HTTP` 串流輸出
* www 是 HTML 網頁目錄
* cctvAgent.py  
  程式進入點，執行後可使用 `help` 檢視可使用的指令
* webSvc.py  
  繼承自 `BaseHTTPRequestHandler` 的 HTTP Web Server 模組
* jfNet 模組是本人另一專案, 請參閱 [SocketTest](https://github.com/Jaofeng/SocketTest)


## *原理說明*
RTSP over HTTP 的原理其實很簡單：

    當終端要求取得影像時，讀取當下的影像(影格)並轉換成圖檔傳送終端

而 `rtspProxy.py` 使用 `OpenCV` 向 `RTSP` 來源拉流(讀取當下影像)，再將讀取的影像經壓縮或調整後，使用 `WebSocket` 或原來的 `HTTP GET Connection` 送至終端瀏覽器，再經由 HTML `img` tag 顯示

以下將以三部分說明：

### *影像擷取*
1. 使用 `OpenCV` 的 `VideoCapture()` 函式開啟 RTSP 串流
2. 依參數進行解析度調整、圖像品質以 `OpenCV` 進行壓縮、放大

### *WebSocket* 傳輸方式
1. 使用 `python-websocket-server` 作為 `WebSocket` 伺服器
2. 終端使用 `rtstProxy(.min).js` 連線至伺服器，連線後，發送請求資料給伺服器
3. 伺服器在接取終端連線，並取得請求的資料後，開始使用 `OpenCV` 自以 `VideoCapture()` 函式所建立的 `camera` 物件中讀取影像(影格)
4. 取得影格後，調整解析度、品質後，再轉換成 JPEG 圖檔內容
5. 將 JPEG 圖檔內容轉換成 `Base64` 字串(*Bytes to Base64，原始大小如 30KBytes，會擴張成 40KBytes，請參閱[維基百科](https://zh.wikipedia.org/wiki/Base64)*)
6. 以 `32KBytes` 為一單位，切割字串內容
7. 傳送給 ***請求同一個 RTSP 的終端 JavaScript***
8. 各終端的 JavaScript 組合這些字串內容後，直接指給 `img.src`

    開發過程中發現傳輸時，常常因為網路品質不佳等原因，容易產生終端(JavaScript WebSocket)解析封包長度錯誤，而造成畫面無法顯示、卡頓、斷線等狀況。
    
    目前暫未研究的錯誤發生原因是因為 `python-websocket-server` 的問題，還是其他問題，所以目前的暫時的解法是：
    ***傳給使用者前，先把 `Base64` 字串以 `32KBytes` 為單位進行切割，到 JavaScript 後，再將之組合，最後指給 `img.src` 顯示***

### *M-JPEG 傳輸方式*
1. 伺服器取得終端的 `img.src` HTTP GET 請求後，先於 `HTTP Header` 中回應 `Content-Type: multipart/x-mixed-replace;boundary={自訂字串}`
2. 再自 `camera` 取得影格，並依傳入的 URL 參數，調整解析度、品質後，再轉換成 JPEG 圖檔內容
3. 於 `HTTP Header` 加上 `Content-Type: image/jpeg`、`Content-Length` 與 `boundary` 後，直接將 JPEG 圖像內容以 `Bytes` 方式傳送至終端
4. 瀏覽器會自動以 `boundary` 拆解圖像內容後餵給 `img`


## *使用說明*
* IP Cam 的 IP 位址與 `Profile ID`，請於 `cctvAgent.py` 與 `index.js` 中設定，或請自行修改成讀取參數檔的方式載入
* 使用 `WebSocket` 傳輸串流時，需搭配 `rtspProxy(.min).js` 使用
* 如需將 `WebSocket` 串流方式提供給非本機連線，請自行將 `index.js` 內的 `cctv.ProxyHost` 修改成本機 IP
* `rtspProxy(.min).js` 與 M-Jpeg 的使用方式，請參閱 `index.js` 內的 **`useRtspProxy()`** 與 **`useHttpMJpegPuller()`** 兩函式
* 終端顯示順暢與否、是否會延遲，取決於原始 RTSP 串流解析度、網路品質、終端顯示解析度等等
* 經在同一封閉網路的不負責實測:satisfied:，對終端設備負載較輕的方式是 M-Jpeg
  * 測試環境設備：
    * Server : MacBook Pro 13" / Mojave 10.14.5
    * Client : tBOX810-838-FL / Debian 10, Kernel 14.2
  * 測試方式：
    * 終端同時開 4 分割畫面，對伺服器請求同一個 IP Cam 影像
  * 測試結果：
    * 以終端顯示的 CPU Usage 而言，WebSocket 高於 M-Jpeg 約 `1.2 倍`
    * 以記憶體用量而言，兩者差不多
    * 以網路流量而言，WebSocket 高於 M-Jpeg 約 `1.4 倍`


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