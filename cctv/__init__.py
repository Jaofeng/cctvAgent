#! /usr/bin/env python3
# -*- coding: UTF-8 -*-

import re
from io import StringIO
from collections import defaultdict
from xml.etree import ElementTree as ET

__all__ = ['AttribDict', 'etree2Dict', 'etreeShortTag', 'xml2Dict']

class AttribDict(dict):
    __slots__ = []

    def __init__(self, **fields):
        for k, v in fields.items():
            if isinstance(v, dict):
                self[k] = AttribDict(**v)
            elif isinstance(v, list):
                self[k] = self.__listDict(v)
            else:
                self[k] = v
            self.__slots__.append(k)

    def __listDict(self, lst):
        res = []
        for item in lst:
            if isinstance(item, list):
                res.append(self.__listDict)
            elif isinstance(item, dict):
                res.append(AttribDict(**item))
            else:
                res.append(item)
        return res

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

    def clone(self):
        return AttribDict(**self)

# XML Methods
def etree2Dict(t):
    '''
    將 xml.etree.Element 節點轉成 dict 型態, 包含屬性與子節點

    傳入:
        `t` `xml.etree.Element` -- 欲轉換的節點

    傳回:
        `dict` -- 轉換完成的 dict 類別

    範例:
        >>> from xml.etree import ElementTree as ET
        >>> from io import StringIO
        >>> xml = """<root xmlns:n="http://a.b.c/Nodes" xmlns:a="http://a.b.c/Attr">
        ...     <n:node a:attr1="true" a:attr2="123">Text</n:node>
        ... </root>"""
        >>> doc = ET.parse(StringIO(xml))
        >>> root = doc.getroot()
        >>> root
        <Element 'root' at 0x103ae1f48>
        >>> root[0]
        <Element '{http://a.b.c/Nodes}node' at 0x103d3a638>
        >>> etree2Dict(root)
        {'root': {'{http://a.b.c/Nodes}node': {'@{http://a.b.c/Attr}attr1': 'true', '@{http://a.b.c/Attr}attr2': '123', '#text': 'Text'}}}
    '''
    d = {t.tag: {} if t.attrib else None}
    children = list(t)
    if children:
        dd = defaultdict(list)
        for dc in map(etree2Dict, children):
            for k, v in dc.items():
                dd[k].append(v)
        d = {t.tag: {k:v[0] if len(v) == 1 else v for k, v in dd.items()}}
    if t.attrib:
        d[t.tag].update(('@' + k, v) for k, v in t.attrib.items())
    if t.text:
        text = t.text.strip()
        if children or t.attrib:
            if text:
                d[t.tag]['#text'] = text
        else:
            d[t.tag] = text
    return d

def etreeShortTag(xml: str):
    '''
    將 XML 格式字串轉換成短標籤格式並傳回 XML NameSpace 清單與 xml.etree.Element 類型

    傳入:
        `xml` `str` -- 原始 XML 字串

    傳回:
        `dict` -- XML NameSpace 內容
        `xml.etree.Element` -- XML 根節點

    範例:
        >>> from xml.etree import ElementTree as ET
        >>> from io import StringIO
        >>> xml = """<root xmlns:n="http://a.b.c/Nodes" xmlns:a="http://a.b.c/Attr">
        ...     <n:node a:attr1="true" a:attr2="123">Text</n:node>
        ... </root>"""
        >>> doc = ET.parse(StringIO(xml))
        >>> doc.getroot()[0].tag
        '{http://a.b.c/Nodes}node'
        >>> doc.getroot()[0].attrib
        {'{http://a.b.c/Attr}attr1': 'true', '{http://a.b.c/Attr}attr2': '123'}
        >>> ns, root = etreeShortTag(xml)
        >>> root[0].tag
        'n:node'
        >>> root[0].attrib
        {'a:attr1': 'true', 'a:attr2': '123'}
        >>> ns
        {'n': 'http://a.b.c/Nodes', 'a': 'http://a.b.c/Attr'}
    '''
    xmlns = dict([(n[0], n[1]) for _, n in ET.iterparse(StringIO(xml), events=['start-ns'])])
    rens = {}
    for k, v in xmlns.items():
        rens[k] = re.compile(f'\\{{{v}\\}}')
    it = ET.iterparse(StringIO(xml))
    for _, t in it:
        for ns, reg in rens.items():
            if reg.match(t.tag):
                if ns:
                    t.tag = reg.sub(f'{ns}:', t.tag)
                else:
                    t.tag = reg.sub('', t.tag)
                break
        for ns, reg in rens.items():
            for k, v in t.attrib.items():
                if reg.match(k):
                    t.attrib[reg.sub(f'{ns}:', k)] = v
                    del t.attrib[k]
    return xmlns, it.root

def xml2Dict(xml: str):
    '''
    將 XML 格式字串轉換成短標籤(Tag)的 dict 類型

    傳入:
        `xml` `str` -- 原始 XML 字串

    傳回:
        `dict` -- dict 結構的 XML 內容

    範例:
        >>> from xml.etree import ElementTree as ET
        >>> from io import StringIO
        >>> xml = """<root xmlns:n="http://a.b.c/Nodes" xmlns:a="http://a.b.c/Attr">
        ...     <n:node a:attr1="true" a:attr2="123">Text</n:node>
        ... </root>"""
        >>> xml2Dict(xml)
        {'root': {'n:node': {'@a:attr1': 'true', '@a:attr2': '123', '#text': 'Text'}}}
    '''
    _, root = etreeShortTag(xml)
    return etree2Dict(root)
