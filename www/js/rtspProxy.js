'use strict';

(function () {
    'use strict';
    var reHead = /::(\d{1,})::/,
        reCont = /~(\d{1,})~/,
        isExit = false,
        clients = [];
    var _ = {};

    function _stop() {
        isExit = true;
        clients.forEach(clt => clt.socket.close());
        clients.splice(0, clients.length);
    }
    function _find(target) {
        var img = $(target);
        return clients.find(clt => $(clt.target).is(img));
    }
    function _connect(target, host, rtsp, width, height) {
        var clt = _find(target);
        if (typeof clt != 'undefined')
            return clt;
        clt = {
            socket: null,
            err: 0,
            packages: 0,
            buffer: [],
            host: host,
            target: $(target),
            rtsp: rtsp,
            resolution: [width, height]
        };
        try {
            var ws = new WebSocket('ws://' + host);
            clt.socket = ws;
            ws.onopen = function (event) {
                console.log('WebSocket opened');
                ws.send(JSON.stringify({
                    'act': 'open',
                    'url': rtsp,
                    'resolution': clt.resolution
                }));
            };
            ws.onmessage = function (event) {
                if (typeof event == 'undefined' || typeof event.data == 'undefined')
                    return;
                try {
                    var tmp = event.data.match(reHead)
                    if (tmp != null) {
                        clt.packages = parseInt(tmp[1]);
                        clt.buffer = []
                    } else {
                        var tmp = event.data.match(reCont);
                        if (tmp == null)
                            return
                        var idx = parseInt(tmp[1])
                        clt.buffer[idx - 1] = event.data.substr(tmp[0].length);
                        if (idx == clt.packages) {
                            $(clt.target).attr('src', clt.buffer.join(''));
                            clt.buffer = []
                        }
                    }
                    clt.err = 0;
                } catch (ex) {
                    console.log('onmessage error: ' + ex);
                }
            };
            ws.onerror = function (event) {
            };
            ws.onclose = function (event) {
                console.log('WebSocket closed');
                clt.socket = null;
                clt.err++;
                var wait = (clt.err > 100) ? 5000 : 1;
                if (isExit) return;
                setTimeout(function () {
                    _.connectTo(target, host, rtsp, width, height);
                }, wait)
            };
        } catch (ex) {
            console.error(ex);
            return null;
        }
        clt.socket = ws;
        return clt;
    }
    _.connectTo = function (target, host, rtsp, width = 0, height = 0) {
        var img = $(target);
        var idx = clients.findIndex(clt => $(clt.target).is(img));
        if (idx != -1) {
            if (typeof clients[idx].socket != 'undefined' && clients[idx].socket != null)
                clients[idx].socket.close();
            clients.splice(idx, 1);
        }
        clients.push(_connect(target, host, rtsp, width, height));
    }
    _.stop = _stop;
    _.find = _find;
    _.resize = function (target, width, height) {
        var clt = _find(target);
        if (typeof clt == 'undefined')
            return;
        clt.resolution = [width, height];
        if (clt.socket != null) {
            try {
                clt.socket.send(JSON.stringify({
                    'act': 'resize',
                    'resolution': clt.resolution
                }));
            } catch (ex) {
                console.error(ex);
            }
        }
    }

    window.rtspProxy = _;
    return _;
})();

$(window).on('beforeunload', function () {
    rtspProxy.stop();
});

