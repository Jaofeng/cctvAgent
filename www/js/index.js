'use strict';

var cctv = {
    ProxyHost: 'localhost:8001',
    Panels: [
        { 'ID': 'A-1', 'OSD': 'OSD 顯示', 'resolution':[640, 480], 'Type': 'ws' },
        { 'ID': 'A-1', 'OSD': 'OSD 顯示', 'resolution':[640, 480], 'Type': 'mjpeg' },
        { 'ID': 'A-1', 'OSD': 'OSD 顯示', 'Type': 'ws' },
        { 'ID': 'A-1', 'OSD': 'OSD 顯示', 'Type': 'mjpeg' }
    ],
    Stream: [
        { 'ID': 'A-1', 'IP': '172.18.0.74', 'Url': 'rtsp://172.18.0.74/onvif-media/media.amp?streamprofile=Profile2&audio=0' },
    ],
}
var selectedCar = 1,
    selectedPanels = 1,
    usePanelStyle = 'OnePanel';

$(document).ready(function () {
    setPanels(cctv.Panels);
    useRtspProxy();
    useHttpMJpegPuller();
});

function setPanels(panels) {
    var canvas = $('.Panels');
    if (panels.length >= 2 && panels.length <= 4) {
        selectedPanels = 4;
        usePanelStyle = 'FourPanel';
    } else if (panels.length >= 5 && panels.length <= 9) {
        selectedPanels = 9;
        usePanelStyle = 'NicePanel';
    } else {
        selectedPanels = 1;
        usePanelStyle = 'OnePanel';
    }
    for (var i = 0; i < selectedPanels; i++) {
        var div = $('<div/>').addClass(usePanelStyle);
        div.resize(function () {
            var lab = $(this).find('label');
            if (typeof lab != 'undefined')
                lab.text($(this).width() + ',' + $(this).height());
        })
        div.appendTo(canvas);
        div.attr({ 'id': 'dCam-' + (i + 1), 'data-no': i });
        var pan = panels[i];
        if (typeof pan != 'undefined' && pan != null) {
            var player = $('<img/>');
            player.attr({ 'id': 'view-' + (i + 1), 'data-id': pan['ID'], 'data-type': pan['Type'] })
                .addClass('VideoFrame')
                .appendTo(div);
            if (typeof pan.resolution != 'undefined' && pan.resolution.length == 2)
                player.attr({'data-resolution': pan.resolution.join('x')})
            var info = cctv.Stream.find(item => item.ID == pan['ID'])
            if (typeof info != 'undefined') {
                player.attr({ 'data-rtsp': info.Url });
                $('<label/>').attr({ 'id': 'osdLT-' + (i + 1) })
                    .addClass('BoxingText Float Left Top')
                    .text(info.ID)
                    .appendTo(div);
                $('<label/>').attr({ 'id': 'osdRT-' + (i + 1) })
                    .addClass('BoxingText Float Right Top')
                    .css({ 'color': 'magenta', 'font-size': '16px' })
                    .appendTo(div);
                if (typeof pan.OSD != 'undefined' && pan.OSD.length != 0) {
                    $('<label/>').attr({ 'id': 'osdRB-' + (i + 1) })
                        .addClass('BoxingText Float Right Bottom')
                        .css({ 'color': 'yellow', 'font-size': '16px' })
                        .text(pan.OSD)
                        .appendTo(div);
                }
            }
        } else {
            div.text('無設定影像來源');
        }
    }
}

function useRtspProxy() {
    // WebSocket Streaming
    if (typeof rtspProxy == 'undefined') {
        console.error('Not Import "rtsyProxy.js"');
        return;
    }
    $('img.VideoFrame[data-Type="ws"]').each(function () {
        var player = $(this);
        if (typeof player.attr('data-rtsp') == 'undefined' || player.attr('data-rtsp').length == 0)
            return;
        var rtsp = player.attr('data-rtsp');
        var resolution = player.attr('data-resolution');
        if (typeof resolution != 'undefined' && resolution.length != 0) {
            var wh = resolution.split('x');
            rtspProxy.connectTo(player, cctv.ProxyHost, rtsp, parseInt(wh[0]), parseInt(wh[1]));
        } else {
            rtspProxy.connectTo(player, cctv.ProxyHost, rtsp);
        }
        var no = parseInt(player.attr('id').split('-')[1]);
        var txt = 'WebSocket, '
        var resolution = player.attr('data-resolution')
        if (typeof resolution != 'undefined')
            txt += resolution;
        else
            txt += 'Default';
        player.parent().find('label[id="osdRT-' + no + '"]').html(txt);
    });
}

function useHttpMJpegPuller() {
    // HTTP M-Jpeg Streaming
    $('img.VideoFrame[data-Type="mjpeg"]').each(function () {
        var player = $(this);
        var resolution = player.attr('data-resolution');
        var url = '/live/' + player.attr('data-id')
        if (typeof resolution != 'undefined' && resolution.length != 0)
            url += '?size=' + resolution;
        player.attr({ 'src': url });
        var no = parseInt(player.attr('id').split('-')[1]);
        var txt = 'M-Jpeg, '
        var resolution = player.attr('data-resolution')
        if (typeof resolution != 'undefined')
            txt += resolution;
        else
            txt += 'Default';
        player.parent().find('label[id="osdRT-' + no + '"]').html(txt);
    });
}
