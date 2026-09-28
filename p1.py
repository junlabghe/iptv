#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPTV 直播源聚合脚本（TVBox / 各类 IPTV 播放器通用）

流程：
  1. 读取 sources.txt 中的公开 M3U 播放列表地址；
  2. 逐个抓取（单源超时 20 秒，失败跳过不影响其它源）；
  3. 解析 #EXTINF 频道名与播放地址（含 #EXTBURL 备用地址、
     以及一条 #EXTINF 下多条地址的写法）；
  4. 只保留 CCTV / 各省卫视 / CHC，过滤购物、成人、境外、广告、测试频道；
  5. 频道名归一化（兼容中英文源），去重，每频道最多保留 3 条不同地址；
  6. 生成 tv.m3u 与 tv.txt，打印统计。

只用 Python 标准库，无第三方依赖。幂等：相同输入必然产生相同输出。

用法：
  python3 iptv_update.py [--out-dir DIR] [--sources FILE]
"""

import argparse
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request

FETCH_TIMEOUT = 20
FETCH_ATTEMPTS = 2
USE_CURL_FALLBACK = True
MAX_URLS_PER_CHANNEL = 3

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

BLOCK_KEYWORDS = [
    "购物", "shopping", "快乐购", "家有购物", "优购物", "风尚购物",
    "中视购物", "环球购物", "好享购物", "东方购物", "央广购物",
    "成人", "adult", "激情", "午夜", "写真", "私密",
    "测试", "试播", "试看", "demo", "sample", "备用", "备播",
    "维护", "即将上线", "招商", "彩条",
    "广告", "adshow",
    "cgtn",
    "中央电视塔", "电视指南",
    "hbo", "cnn", "bbc", "nhk", "tvb", "凤凰", "澳亚", "华娱",
    "discovery", "espn", "fox", "mtv", "animax", "cartoon",
    "arirang", "france 24", "al jazeera", "半岛",
    "星空", "香港卫视", "人间",
    "上海卫视",
]
