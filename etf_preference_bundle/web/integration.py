# -*- coding: utf-8 -*-
"""
（轉接層）網頁版的交付鉤子。

實際的接點在 bundle 根目錄的 recommender_hook.py —— 請改那個檔,不要改這裡。
這裡只是把它 re-export 給 web/app.py 使用,讓網頁版與函式庫版共用同一個接點。
"""
from recommender_hook import deliver_weights  # noqa: F401  ← 改 recommender_hook.py
