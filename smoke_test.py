#!/usr/bin/env python3
"""
smoke_test.py — kose-scraper's offline suite
=============================================
One file of plain functions with inline fixtures. No pytest, no conftest, no
fixtures directory; `tests/test_smoke.py` wraps this as a single pytest test
so `pytest` works as an entry point without a second copy of the checks.

    python3 smoke_test.py          # everything
    python3 smoke_test.py -v       # and say what each check looked at

It must pass with NO engine library installed at all: every
`import playwright_scraper` / `selenium_scraper` / `puppeteer_scraper` is
guarded and the skip is RECORDED, because "skipped, engine absent" reads
identically to a real import error. CI installs each engine in its own venv
and fails if that engine's group reports a skip.

The fixtures
------------
Every one is cut VERBATIM from a real capture taken 2026-09-18 and trimmed to
the parts the parser reads. Each was verified to parse to IDENTICAL values to
its untrimmed original before being committed: the trimming
script asserted field-by-field equality on every row, not merely that the row
count matched.

    LISTING_HTML         /site/cosmedecorte/c/c15/, 4 of its 24 tiles —
                         three unavailable and one in stock, so `in_stock`
                         is checked against a page that really has both
                         values on it. Prices run 3,300 to 264,000 yen.
    LISTING_TAX8_HTML    /c/c15_p10/, the one page in the captures carrying
                         Japan's REDUCED 8% consumption-tax rate. Two tiles
                         in 171 had it, and a consumer computing a pre-tax
                         figure from the standard rate is wrong in silence.
    TAGS_HTML            /site/itemtags/list.aspx?tags=…, two tiles of two
                         DIFFERENT brands — the route that crosses brands,
                         which is why `brand` is read per tile.
    PRODUCT_HTML         one ONE BY KOSE product: its JSON-LD `Product`
                         block, its price node, its breadcrumb, its colour
                         list — and, deliberately, one of the staff-review
                         cards that reuse the class `c-product__item` on a
                         `<div>`, plus an `awoo` recommendation block. A
                         class-only tile selector invents products out of
                         both; this fixture is what pins that it does not.
    EMPTY_HTML           a listing the site served with no tiles on it: a
                         tag facet walked past its end. An ANSWER, not a
                         failure.
    NOTFOUND_HTML        a BOGUS GOODS CODE — `/site/x/g/gZZZZZZ/`, which
                         this site answers with HTTP **200** and its full
                         chrome, not with a 404. It carries exactly one
                         product-shaped link, which is why the parse-failure
                         threshold is two. An earlier version of this fixture
                         was written by hand with a 404 title on it, and was
                         wrong about the one thing it existed to show (a
                         guard is only as good as the fixture it runs
                         against).
    HTTP404_HTML         the site's REAL 404, verbatim from
                         `/definitely-not-a-page`: 1,040 bytes, no site
                         chrome at all, and the status stated in its own
                         <title>. That last part is what lets Selenium — which
                         cannot read an HTTP status — agree with its twins.
    CHROMIUM_ERROR_HTML  Chromium's own network-error page. It carries
                         `<title>maison.kose.co.jp</title>` — the site's own
                         hostname — and no vendor marker at all, which is
                         why positive-asset detection is the only thing that
                         classifies it correctly.

No personal data appears in any of them. Maison KOSÉ does publish staff
opinion pieces under real first names, and the one staff card in
PRODUCT_HTML is there because the PARSER must ignore it — so the author's
name and the review text are replaced with obvious placeholders while the
markup the site generates around them is left untouched.
`check_fixtures_carry_no_session_material` guards the next capture by
PATTERN rather than by these literals.
"""

import argparse
import ast
import csv
import inspect
import io
import glob
import json
import os
import re
import subprocess
import stat
import sys
import tempfile
from dataclasses import asdict, fields

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import env_config
import output_writer
import page_flow
import product_parser
import proxy_pool
from output_writer import Product

FAILURES = []
PASSED = 0
SKIPS = []
VERBOSE = False


def check(name, condition, detail=""):
    global PASSED
    if condition:
        PASSED += 1
        if VERBOSE:
            print("  ok   %s%s" % (name, (" — " + str(detail)) if detail else ""))
    else:
        FAILURES.append("%s%s" % (name, (" — " + str(detail)) if detail else ""))
        print("  FAIL %s%s" % (name, (" — " + str(detail)) if detail else ""))


def equal(name, got, want):
    check(name, got == want, "got %r, want %r" % (got, want))


def skip(group, reason):
    SKIPS.append("%s: %s" % (group, reason))


LISTING_URL = "https://maison.kose.co.jp/site/cosmedecorte/c/c15/"
TAGS_URL = ("https://maison.kose.co.jp/site/itemtags/list.aspx"
            "?tags=%E3%82%B7%E3%83%AF%E6%94%B9%E5%96%84,%E3%82%B9%E3%82%AD%E3%83%B3%E3%82%B1%E3%82%A2")
PRODUCT_URL = "https://maison.kose.co.jp/site/onebykose/g/gMUSC/"

LISTING_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<meta name="keywords" content="1／13ページMaison KOSE">
<link rel="canonical" href="https://maison.kose.co.jp/site/cosmedecorte/c/c15/">
<link rel="next" href="https://maison.kose.co.jp/site/cosmedecorte/c/c15_p2/">
<title>コスメデコルテ｜ Maison KOS&#201;(メゾンコーセー)</title>
<link rel="stylesheet" href="/freepage/maison-kose/common/css/style.css">
<script src="/js/sys/goods_filter.js"></script>
<script src="/js/sys/cart.js"></script>
</head><body>
<ul class="c-product-content__list js-goods-list-wrapper list-modal-trigger">
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/new.png" alt="NEW"></span>
    
    
  </p>
  <div class="c-product__thumb is-new">
    <a href="/site/cosmedecorte/g/gJQBA/" class="c-product__thumb__img">
      <img src="/img/goods/S/JQBA_sub.png" alt="AQ ミリオリティ ザ クリーム デコラシオン ＜60g＞" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=JQBA&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gJQBA/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      AQ ミリオリティ ザ クリーム デコラシオン ＜60g＞
    </p>
    </a>

    <p class="c-product__price">
    
         264,000円<span>（税込）</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-no-purchase">現在購入頂けません</a>
  </div>
  
</li>
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/new.png" alt="NEW"></span>
    
    
  </p>
  <div class="c-product__thumb is-new">
    <a href="/site/cosmedecorte/g/gJQGA/" class="c-product__thumb__img">
      <img src="/img/goods/S/JQGA_sub.png" alt="AQ ミリオリティ ザ クリーム デコラシオン ＜20g＞" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=JQGA&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gJQGA/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      AQ ミリオリティ ザ クリーム デコラシオン ＜20g＞
    </p>
    </a>

    <p class="c-product__price">
    
         99,000円<span>（税込）</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-no-purchase">現在購入頂けません</a>
  </div>
  
</li>
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/new.png" alt="NEW"></span>
    
    
  </p>
  <div class="c-product__thumb is-new">
    <a href="/site/cosmedecorte/g/gJQGB/" class="c-product__thumb__img">
      <img src="/img/goods/S/JQGB_sub.png" alt="AQ ミリオリティ ザ クリーム デコラシオン ＜60g＞" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=JQGB&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gJQGB/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      AQ ミリオリティ ザ クリーム デコラシオン ＜60g＞
    </p>
    </a>

    <p class="c-product__price">
    
         198,000円<span>（税込）</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-no-purchase">現在購入頂けません</a>
  </div>
  
</li>
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    
  </p>
  <div class="c-product__thumb">
    <a href="/site/cosmedecorte/g/gJQIO/" class="c-product__thumb__img">
      <img src="/img/goods/S/JQIO_sub.png" alt="キモノ マイ ウォーターコロン ＜15mL＞" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=JQIO&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gJQIO/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      キモノ マイ ウォーターコロン ＜15mL＞
    </p>
    </a>

    <p class="c-product__price">
    
         3,300円<span>（税込）※</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-select list-modal-button" href="javascript:void(0);" data-module="CommonModal" data-options='{ "target":"JQIO_vda3u8m6gf" }'>種類を選ぶ</a>
  </div>
  <div class="c-common-modal p-product-detail__modal-makeup list-modal-box" data-module-commonmodal-target="JQIO_vda3u8m6gf">
    <div class="c-common-modal__background list-modal-bg" data-module-commonmodal-close="JQIO_vda3u8m6gf"></div>
    <div class="c-common-modal__inner p-product-detail__modal-makeup__inner list-modal-inner" data-ref-goods="JQIO">
      <a href="javascript:void(0)" class="c-common-modal__closebtn p-product-detail__modal-makeup__closebtn" data-module-commonmodal-close="JQIO_vda3u8m6gf"></a>
      <div class="list-modal-block"><figure class="img-center"><img src="/img/sys/loading.gif"></figure></div>
    </div>
  </div>
  
</li>
</ul>
</body></html>"""

LISTING_TAX8_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<meta name="keywords" content="10／13ページMaison KOSE">
<link rel="canonical" href="https://maison.kose.co.jp/site/cosmedecorte/c/c15/">
<link rel="next" href="https://maison.kose.co.jp/site/cosmedecorte/c/c15_p11/">
<title>コスメデコルテ｜ Maison KOS&#201;(メゾンコーセー)</title>
<link rel="stylesheet" href="/freepage/maison-kose/common/css/style.css">
<script src="/js/sys/goods_filter.js"></script>
<script src="/js/sys/cart.js"></script>
</head><body>
<ul class="c-product-content__list js-goods-list-wrapper">
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    
  </p>
  <div class="c-product__thumb">
    <a href="/site/cosmedecorte/g/gJLAT/" class="c-product__thumb__img">
      <img src="/img/goods/S/JLAT_sub.png" alt="ホワイトロジスト オーバーナイト インナー プラス" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=JLAT&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gJLAT/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      ホワイトロジスト オーバーナイト インナー プラス
    </p>
    </a>

    <p class="c-product__price">
    
         3,024円<span>（税込/8%）※</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-animation-add-cart js-enhanced-ecommerce-add-cart block-list-add-cart-btn-purchase js-cart-in-trigger verification_goods" data-target="product-01" href="https://maison.kose.co.jp/site/cart/cart.aspx?goods=JLAT">
      <input type="hidden" value="JLAT" class="cart_hidden_goods">
      カートに入れる
    </a>
  </div>
  
</li>
</ul>
</body></html>"""

TAGS_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<link rel="canonical" href="https://maison.kose.co.jp/site/itemtags/list.aspx?tags=%E3%82%B7%E3%83%AF%E6%94%B9%E5%96%84,%E3%82%B9%E3%82%AD%E3%83%B3%E3%82%B1%E3%82%A2">
<title>シワ改善 スキンケア ｜ Maison KOS&#201;(メゾンコーセー)</title>
<script src="/js/sys/goods_filter.js"></script>
<link rel="stylesheet" href="/freepage/maison-kose/common/css/style.css">
</head><body>
<ul class="c-product-content__list js-goods-list-wrapper">
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/new.png" alt="NEW"></span>
    
    <span class="c-product__icon c-product__icon-limited"><img src="/img/icon/limited.png" alt="限定品"></span>
    
  </p>
  <div class="c-product__thumb is-new">
    <a href="https://maison.kose.co.jp/site/infinity/g/gBAQQ/" class="c-product__thumb__img">
      <img src="https://maison.kose.co.jp/img/goods/L/BAQQ_main.png" alt="ザ リペア トータル ケア キット" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=BAQQ&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">インフィニティ</p>
    <a href="https://maison.kose.co.jp/site/infinity/g/gBAQQ/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      ザ リペア トータル ケア キット
    </p>
    </a>
    <p class="c-product__price">
    
         16,060円<span>（税込）※</span>
    
    </p>
  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-animation-add-cart js-enhanced-ecommerce-add-cart block-list-add-cart-btn-purchase" href="https://maison.kose.co.jp/site/cart/cart.aspx?goods=BAQQ">商品を購入する</a>
  </div>
  
</li>
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/new.png" alt="NEW"></span>
    
    
  </p>
  <div class="c-product__thumb is-new">
    <a href="https://maison.kose.co.jp/site/carte/g/gPHGN/" class="c-product__thumb__img">
      <img src="https://maison.kose.co.jp/img/goods/L/PHGN_main.png" alt="シワ改善・シミ予防ケア　高保湿オールインワンゲル" />
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=PHGN&crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about">
    
    <p class="c-product__brand">カルテHD</p>
    <a href="https://maison.kose.co.jp/site/carte/g/gPHGN/">
    <p class="c-product__product-name" data-module="TruncateText" data-options='{ "length": 36 }'>
      シワ改善・シミ予防ケア　高保湿オールインワンゲル
    </p>
    </a>
    <p class="c-product__price">
    
         3,520円<span>（税込）※</span>
    
    </p>
  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-animation-add-cart js-enhanced-ecommerce-add-cart block-list-add-cart-btn-select list-modal-button" href="javascript:void(0);" data-module="CommonModal" data-options='{ "target":"PHGN_f1woi6vsg2" }'>種類を選ぶ</a>
  </div>
  <div class="c-common-modal p-product-detail__modal-makeup list-modal-box" data-module-commonmodal-target="PHGN_f1woi6vsg2">
    <div class="c-common-modal__background list-modal-bg" data-module-commonmodal-close="PHGN_f1woi6vsg2"></div>
    <div class="c-common-modal__inner p-product-detail__modal-makeup__inner list-modal-inner" data-ref-goods="PHGN">
      <a href="javascript:void(0)" class="c-common-modal__closebtn p-product-detail__modal-makeup__closebtn" data-module-commonmodal-close="PHGN_f1woi6vsg2"></a>
      <div class="list-modal-block"><figure class="img-center"><img src="/img/sys/loading.gif"></figure></div>
    </div>
  </div>
  
</li>
</ul>
</body></html>"""

PRODUCT_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<link rel="canonical" href="https://maison.kose.co.jp/site/onebykose/g/gMUSC/">
<title>セラム シールド ＜40g＞｜ Maison KOS&#201;</title>
<script type="application/ld+json">
{
   "@context":"http:\\/\\/schema.org\\/",
   "@type":"Product",
   "name":"セラム シールド ＜40g＞",
   "image":"https:\\u002f\\u002fmaison.kose.co.jp\\u002fimg\\u002fgoods\\u002fS\\u002fMUSC_sub_BC-2.png",
   "description":"日本初&lt;span style=\\u0022font-size: 10px;line-height:1.3;\\u0022&gt;＊1&lt;\\u002fspan&gt;、うるおい改善＋シワ改善&lt;br \\u002f&gt;根深い渇きに高保水膜 &lt;span style=\\u0022font-size: 10px;line-height:1.3;\\u0022&gt;[医薬部外品]&lt;\\u002fspan&gt;",
   "mpn":"MUSC",
   "sku":"MUSC",
   "releaseDate":"2023/08/21",
   "offers":{
      "@type":"Offer",
      "price":5940,
      "priceCurrency":"JPY",
      "availability":"http:\\/\\/schema.org\\/InStock"
   },
   "isSimilarTo":{
      "@type":"Product",
      "name":"セラム シールド ＜40g＞",
      "image":"https:\\u002f\\u002fmaison.kose.co.jp\\u002fimg\\u002fgoods\\u002fS\\u002fMUSC_sub_BC-2.png",
      "mpn":"MUSC",
      "url":"https:\\u002f\\u002fmaison.kose.co.jp\\u002fsite\\u002fonebykose\\u002fg\\u002fgMUSC\\u002f"
   }
}
</script>
<script src="/js/sys/cart.js"></script>
<link rel="stylesheet" href="/freepage/maison-kose/common/css/style.css">
</head><body>
<ul class="c-breadcrumb">
<li class="c-breadcrumb__item">
      <a href="https://maison.kose.co.jp/">TOP</a>
  </li>
<li class="c-breadcrumb__item">
  <span class="breadcrumb__item__arrow"></span>
  <a href="/site/onebykose/c/c54/"><span>ONE BY KOSE</span></a>
</li>
<li class="c-breadcrumb__item">
  <span class="breadcrumb__item__arrow"></span>
  <a href="/site/onebykose/c/c5410/"><span>スキンケア</span></a>
</li>
<li class="c-breadcrumb__item">
  <span class="breadcrumb__item__arrow"></span>
  <a href="/site/onebykose/c/c541040/"><span>クリーム</span></a>
</li>
<li class="c-breadcrumb__item">
  <span class="breadcrumb__item__arrow"></span>
  <a href="/site/onebykose/g/gMUSC/"><span>セラム シールド ＜40g＞</span></a>
</li>
</ul>
<div class="p-product-detail__item">
<div class="p-product-detail__item__price">
            Maison KOS&Eacute;販売価格　<span> 5,940円</span>（税込）
          </div>
<div class="p-product-detail__item__variation">
            <span class="p-product-detail__item__net">容量 40g</span></div>
<ul class="p-product-detail__color__list">
<li class="p-product-detail__color__group__item color_id_0" data-navi-id="0"></li>
<li class="p-product-detail__color__group__item color_id_1" data-navi-id="1"></li>
</ul>
</div>
<!-- the staff-review block: `c-product__item` on a DIV, not an LI -->
<div class="c-product-slider__products">
<div class="c-product__item">
	<a href="/staff/skincaredetail/c00000000" class="p-product-detail__staffstart__hover-action">
		<div class="p-product-detail__staffstart__image">
			<img src="https://static.staff-start.com/img/coordinates/00/PLACEHOLDER_IMAGE_ID/PLACEHOLDER_FILE_l.jpg" alt="">
		</div>
	</a>
	<div class="p-product-detail__staffstart__texts">
		<p class="p-product-detail__staffstart__title">
			<a class="p-product-detail__staffstart__hover-action" href="/staff/skincaredetail/c00000000" data-module="TruncateText" data-options='{"length":20}'>PLACEHOLDER staff opinion text — the real one was a named employee's own
writing and is not republished here. The MARKUP is what this fixture is for:
this card carries the class `c-product__item` on a DIV, and the parser must
see zero products in it.</a>
		</p>
		<p class="p-product-detail__staffstart__author">PLACEHOLDER_AUTHOR</p>
	</div>
</div>
</div>
<div class="awoo-product-list"><p class="awoo-product-name">別の商品</p><p class="awoo-product-price">1,100円</p></div>
</body></html>"""

HTTP404_HTML = """﻿<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>404- ページが見つかりません。</title>
<style type="text/css">
<!--
/* CSS layout */

body {
	margin: 0;
	padding: 0;
	color: #444;
}

.block-custom-error-404 {
	width: 500px;
	text-align: center;
	margin: 50px auto 0 auto;
	padding: 30px;
	border: 1px solid #808080;
}

.block-custom-error-404--title {
	font-weight: bold;
}

-->
</style>
</head>
<body class="page-customerror">
<div class="wrapper">
	<div class="pane-contents">
		<div class="container">
			<main class="pane-main">
				<div class="block-custom-error-404">
					<p class="block-custom-error-404--title">大変申し訳ありませんが、該当ページがございません。</p>
					<p class="block-custom-error-404--top"><a href="/" target="_self">トップページ</a>へご案内いたします。</p>
					<p class="block-custom-error-404--message">このページをブックマーク登録されていた方は、お手数ですがブックマークの変更をお願いいたします。</p>
					<a class="block-custom-error-404--history-back" href="javascript:void(0)" onclick="javascript:history.go(-1)">戻る</a>
				</div>
			</main>
		</div>
	</div>
</div>
</body>
</html>
"""

CDP_PAGE_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<title>コスメデコルテ｜ Maison KOSÉ(メゾンコーセー)</title>
<link rel="canonical" href="https://maison.kose.co.jp/site/cosmedecorte/c/c15/">
<script src="/js/sys/common.js"></script>
<script src="/js/sys/search_suggest.js"></script>
<script src="/js/sys/sys.js"></script>
<!-- injected by 2Captcha's Scraping Browser auto-solve extension, verbatim -->
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/captchafox/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/mt_captcha/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/turnstile/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/turnstile/hunter.js" data-ts-input="cf-turnstile-response"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/amazon_waf/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/yandex/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/lemin/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/arkoselabs/hunter.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/arkoselabs/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/recaptcha/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/recaptcha/hunter.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/keycaptcha/hunter.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/geetest_v4/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/captcha/geetest/interceptor.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/communication_helpers.js"></script>
<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo/content/core_helpers.js"></script>
</head><body>
<captcha-widgets></captcha-widgets>
<ul class="c-product-content__list js-goods-list-wrapper">
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap" style="min-height: 20px;">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/comingsoon.png" alt="COMING SOON"></span>
    <span class="c-product__icon c-product__icon-limited"><img src="/img/icon/limited.png" alt="限定品"></span>
    
    <span class="c-product__launch-date">11月1日発売</span>
  </p>
  <div class="c-product__thumb is-soon">
    <a href="/site/cosmedecorte/g/gCDS0465/" class="c-product__thumb__img">
      <img src="/img/goods/S/CDS0465_sub.png" alt="リポソーム アドバンスト リペアセラム パープルリボン セット 2026">
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=CDS0465&amp;crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about" style="min-height: 145px;">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gCDS0465/">
    <p class="c-product__product-name" data-module="TruncateText" data-options="{ &quot;length&quot;: 36 }">
      リポソーム アドバンスト リペアセラム パープルリボン セット 2026
    </p><div style="height: 35px;"><div data-revico-goods="CDS0465" data-revico-layout="pc-goods-list-star"></div></div>
    </a>

    <p class="c-product__price">
    
         17,600円<span>（税込）</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-no-purchase">現在購入頂けません</a>
  </div>
  
</li>
<li class="c-product__item is-item-number-1">
  <p class="c-product__icon__wrap" style="min-height: 20px;">
    <span class="c-product__icon c-product__icon-limited"><img src="/freepage/maison-kose/common/img/badge/comingsoon.png" alt="COMING SOON"></span>
    <span class="c-product__icon c-product__icon-limited"><img src="/img/icon/limited.png" alt="限定品"></span>
    
    <span class="c-product__launch-date">11月1日発売</span>
  </p>
  <div class="c-product__thumb is-soon">
    <a href="/site/cosmedecorte/g/gCDS0466/" class="c-product__thumb__img">
      <img src="/img/goods/S/CDS0466_sub.png" alt="リポソーム アドバンスト リペアクリーム パープルリボン セット 2026">
    </a>
    <a class="block-page-favorite--btn block-item-detail-favorite js-animation-bookmark" href="javascript:location.href='https://maison.kose.co.jp/site/customer/bookmark.aspx?goods=CDS0466&amp;crsirefo_hidden='+ jQuery('#js_crsirefo_hidden').val()">
      <div class="c-favorite-btn" data-module="Favorite">
        <img src="/freepage/maison-kose/common/img/common/favorite/like.png" class="c-favorite-btn__img" alt="">
      </div>
    </a>
  </div>
  <div class="c-product__about" style="min-height: 145px;">
    
    <p class="c-product__brand">コスメデコルテ</p>
    <a href="/site/cosmedecorte/g/gCDS0466/">
    <p class="c-product__product-name" data-module="TruncateText" data-options="{ &quot;length&quot;: 36 }">リポソーム アドバンスト リペアクリーム パープルリボン セット 20…</p><div style="height: 35px;"><div data-revico-goods="CDS0466" data-revico-layout="pc-goods-list-star"></div></div>
    </a>

    <p class="c-product__price">
    
         12,100円<span>（税込）</span>
    
    </p>

  </div>
  <div class="c-product__hashtag-area">
    
  </div>

  
  <div class="btn-items-cart">
    <a class="block-list-add-cart-btn js-enhanced-ecommerce-add-cart block-list-add-cart-btn-no-purchase">現在購入頂けません</a>
  </div>
  
</li>
</ul>
</body></html>"""

EMPTY_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<title>シワ改善 スキンケア ｜ Maison KOS&#201;(メゾンコーセー)</title>
<script src="/js/sys/goods_filter.js"></script>
<link rel="stylesheet" href="/freepage/maison-kose/common/css/style.css">
</head><body>
<div class="l-main__content"></div>
</body></html>"""

NOTFOUND_HTML = """<!doctype html><html lang="ja"><head>
<meta charset="UTF-8">
<title>｜ Maison KOS&#201;(メゾンコーセー)</title>
<script src="/js/sys/common.js?t=1"></script>
<script src="/js/sys/search_suggest.js"></script>
<script src="/js/sys/sys.js"></script>
<link rel="stylesheet" href="//d3e9wwnbfrsolq.cloudfront.net/freepage/maison-kose/css/style_pc.css">
<link rel="stylesheet" href="//d3e9wwnbfrsolq.cloudfront.net/freepage/maison-kose/css/pc_add__dev.css?2409">
</head><body>
<div class="l-main__content"></div>
<a href="https://maison.kose.co.jp/site/g/gZZZZZZ/">おすすめ</a>
</body></html>"""

CHROMIUM_ERROR_HTML = """<html><head><title>maison.kose.co.jp</title></head><body><div id="main-frame-error"><span jscontent="heading.msg">このサイトにアクセスできません</span><div class="error-code">ERR_PROXY_CONNECTION_FAILED</div></div></body></html>"""

# ---------------------------------------------------------------------------
# Family constants
# ---------------------------------------------------------------------------

ENGINES = ("playwright_scraper", "selenium_scraper", "puppeteer_scraper")
DRIVER_IMPORTS = {
    "playwright_scraper": "playwright",
    "selenium_scraper": "selenium",
    "puppeteer_scraper": "pyppeteer",
}

# The family's flag contract, plus the five it omitted for
# months while nearly every repo shipped them. Re-derive rather than trusting
# this comment:
#
#   grep -ohE '"--[a-z0-9-]+"' */playwright_scraper.py | sort | uniq -c | sort -rn
CONTRACT_FLAGS = {
    "--url", "--pages", "--category", "--format", "--out", "--delay",
    "--retries", "--retry-delay", "--concurrency", "--proxy", "--proxy-file",
    "--proxy-rotate", "--proxy-shuffle", "--proxy-block-retries",
    "--twocaptcha-key", "--captcha-api", "--solve-captcha", "--min-score",
    "--cdp-endpoint", "--allow-empty", "--dump-html",
    "--fingerprint", "--fp-tags", "--fp-country", "--mode",
}

# `--locale` is in 16 of the 18 repos counted and is deliberately ABSENT
# here, which is a measurement rather than an oversight: maison.kose.co.jp
# is one market — no hreflang set, no /en/ route, JPY on every row — so the
# flag would be a setting that changes nothing, which is exactly what to avoid.
#
# `--sort` is absent for the same reason: the site offers no ordering control
# on either listing route. That is the opposite of bbb-scraper, where the
# ordering decides WHICH rows are in the file and therefore had to exist.
#
# `--tags` is this repo's own addition, for the one listing route that
# crosses brands.
EXTRA_FLAGS = {"--tags", "--headless", "--headful"}

# The name the shared flag-parity check uses.
FAMILY_FLAGS = CONTRACT_FLAGS

BANNED_FLAGS = ("--antidetect", "--country-code", "--country", "--locale", "--sort")

# Assembled from pieces rather than written out, so that this file can be
# SCANNED for them too: three repos in the family exempted
# `smoke_test.py` wholesale, which made the file most likely to acquire a
# stray phrase the one file nobody checked.
BANNED_WORDING = (
    "cloud" + " browser",
    "anti" + "detect browser",
    "2scraper Anti" + "detect Browser",
    "gate." + "2prx.com",
    "ANTI" + "DETECT_LOCAL_API",
)

_TREE_BEFORE = None



# ---------------------------------------------------------------------------
# The parser, against real captures. Assert VALUES, not coverage.
# ---------------------------------------------------------------------------

def check_listing_parses_with_the_values_the_page_shows():
    rows = product_parser.parse_products(LISTING_HTML, LISTING_URL, page=1)
    equal("listing row count", len(rows), 4)
    equal("first sku", rows[0].sku, "JQBA")
    equal("first title", rows[0].title,
          "AQ ミリオリティ ザ クリーム デコラシオン ＜60g＞")
    equal("first brand", rows[0].brand, "コスメデコルテ")
    # A six-figure yen price, which is where a naive comma-stripping parser
    # goes wrong: 264,000 must not become 264 or 264000000.
    equal("first price", rows[0].price, 264000.0)
    equal("first currency", rows[0].currency, "JPY")
    equal("first tax rate", rows[0].tax_rate, 10)
    equal("first image", rows[0].image_url,
          "https://maison.kose.co.jp/img/goods/S/JQBA_sub.png")
    equal("first url", rows[0].url,
          "https://maison.kose.co.jp/site/cosmedecorte/g/gJQBA/")
    equal("price source", rows[0].price_source, "tile")
    equal("category from the URL", rows[0].category, "c15")
    equal("badges", rows[0].badges, "new")
    equal("positions restart at 1 and count up",
          [r.position for r in rows], [1, 2, 3, 4])
    equal("page threaded through", {r.page for r in rows}, {1})
    equal("prices across the fixture", [r.price for r in rows],
          [264000.0, 99000.0, 198000.0, 3300.0])


def check_the_image_is_the_product_and_not_the_badge():
    """The first `<img>` in a tile is a merchandising badge, not the product.

    The first version of this parser read it and got
    `/freepage/…/badge/new.png` on every tile that had one — 100% coverage of
    the WRONG value, which is why values are asserted rather
    than coverage. Every row here must point at `/img/goods/`.
    """
    rows = product_parser.parse_products(LISTING_HTML, LISTING_URL)
    bad = [r.sku for r in rows if r.image_url and "/badge/" in r.image_url]
    check("no row carries a badge image as its product image", not bad, str(bad))
    check("every row's image is a goods image",
          all("/img/goods/" in (r.image_url or "") for r in rows),
          str([r.image_url for r in rows]))
    check("the badge is still in the fixture, so this check can fail",
          "/badge/new.png" in LISTING_HTML)


def check_stock_is_an_allowlist_and_takes_both_values():
    """A column you never saw take its other value is not verified."""
    rows = product_parser.parse_products(LISTING_HTML, LISTING_URL)
    equal("in_stock across the fixture", [r.in_stock for r in rows],
          [False, False, False, True])
    check("the fixture really contains both CTA wordings",
          "現在購入頂けません" in LISTING_HTML and "種類を選ぶ" in LISTING_HTML)


def check_an_unknown_cta_wording_reads_as_unknown_not_as_in_stock():
    """A wording the site adds tomorrow must under-report, never invent stock."""
    html = LISTING_HTML.replace("種類を選ぶ", "なにか新しい文言")
    rows = product_parser.parse_products(html, LISTING_URL)
    equal("an unrecognised CTA gives None, not True",
          rows[3].in_stock, None)


def check_the_reduced_tax_rate_is_read():
    rows = product_parser.parse_products(LISTING_TAX8_HTML, LISTING_URL)
    equal("reduced-rate row count", len(rows), 1)
    equal("reduced rate", rows[0].tax_rate, 8)
    equal("its price", rows[0].price, 3024.0)
    equal("a bare （税込） still means the standard rate",
          product_parser.parse_tax_rate("1,234円（税込）"), 10)
    equal("no tax annotation at all is None, never a guessed 10",
          product_parser.parse_tax_rate("1,234円"), None)


def check_the_store_price_marker_is_recorded():
    rows = product_parser.parse_products(LISTING_TAX8_HTML, LISTING_URL)
    equal("※ marks the store's own selling price",
          rows[0].price_is_store_price, True)
    plain = product_parser.parse_products(LISTING_HTML, LISTING_URL)
    equal("its absence is None rather than False",
          plain[0].price_is_store_price, None)


def check_a_tag_listing_mixes_brands_and_is_read_per_tile():
    rows = product_parser.parse_products(TAGS_HTML, TAGS_URL, page=1)
    equal("tag row count", len(rows), 2)
    check("the two tiles carry DIFFERENT brands",
          rows[0].brand != rows[1].brand,
          "%r vs %r" % (rows[0].brand, rows[1].brand))
    check("neither brand came from the URL, which names no brand at all",
          "itemtags" in TAGS_URL and rows[0].brand not in TAGS_URL)
    equal("a tag URL yields no cNN category", rows[0].category, None)


def check_a_product_page_is_not_a_listing():
    """The `li.` in the tile selector is the whole guard.

    A product page reuses `c-product__item` on `<div>`s for staff-review
    cards. A class-only selector would emit one row per card — a product
    with a `/staff/` URL and no sku — which is junk-link data theft in a new
    costume. This pins both directions.
    """
    equal("the class really is present on the product page",
          PRODUCT_HTML.count("c-product__item") >= 2, True)
    equal("but no LI tile is", product_parser.tile_count(PRODUCT_HTML), 0)
    equal("so the listing parser finds nothing on it",
          len(product_parser.parse_products(PRODUCT_HTML, PRODUCT_URL)), 0)
    check("and the awoo recommendation block is present too, unread",
          "awoo-product-name" in PRODUCT_HTML)


def check_product_detail_reads_the_pages_own_jsonld():
    rows = product_parser.parse_product_detail(PRODUCT_HTML, PRODUCT_URL)
    equal("one row per product page", len(rows), 1)
    row = rows[0]
    equal("sku", row.sku, "MUSC")
    equal("title", row.title, "セラム シールド ＜40g＞")
    equal("price", row.price, 5940.0)
    equal("currency", row.currency, "JPY")
    equal("price source", row.price_source, "jsonld")
    equal("in stock", row.in_stock, True)
    equal("brand from the breadcrumb", row.brand, "ONE BY KOSE")
    equal("category from the breadcrumb", row.category, "スキンケア")
    equal("subcategory from the breadcrumb", row.subcategory, "クリーム")
    equal("volume", row.volume, "40g")
    equal("colour count", row.colour_count, 2)
    equal("release date, verbatim", row.release_date, "2023/08/21")
    equal("mode", row.mode, "product")


def check_the_structured_and_displayed_prices_agree():
    """CHECK this on every site rather than assume it."""
    equal("they agree on the captured product",
          product_parser.detail_price_agrees(PRODUCT_HTML), True)
    broken = PRODUCT_HTML.replace("5,940円", "9,999円")
    equal("and a disagreement is reported rather than smoothed over",
          product_parser.detail_price_agrees(broken), False)
    equal("a missing figure is unknown, not a mismatch",
          product_parser.detail_price_agrees(EMPTY_HTML), None)


def check_a_product_row_never_links_to_a_DIFFERENT_product():
    """5 of 20 product pages canonicalise to a sibling sku (measured).

    Using the canonical as the row's URL would have produced a quarter of
    all rows whose link opens a different product while their title, sku and
    price describe this one.
    """
    html = PRODUCT_HTML.replace(
        '<link rel="canonical" href="https://maison.kose.co.jp/site/onebykose/g/gMUSC/">',
        '<link rel="canonical" href="https://maison.kose.co.jp/site/onebykose/g/gMUSX/">')
    row = product_parser.parse_product_detail(html, PRODUCT_URL)[0]
    equal("the row's URL names the row's own sku",
          product_parser.sku_from_url(row.url), row.sku)
    equal("and the canonical's sku is kept as the family link",
          row.variant_of, "MUSX")
    row2 = product_parser.parse_product_detail(PRODUCT_HTML, PRODUCT_URL)[0]
    equal("a self-canonicalising page has no variant_of",
          row2.variant_of, None)


# ---------------------------------------------------------------------------
# URLs and pagination
# ---------------------------------------------------------------------------

def check_url_shapes_and_routes():
    cases = [
        ("https://maison.kose.co.jp/site/cosmedecorte/c/c15/", "category", "c15", None),
        ("https://maison.kose.co.jp/site/c/c21/", "category", "c21", None),
        ("https://maison.kose.co.jp/site/x/c/c15_p7/", "category", "c15", None),
        ("https://maison.kose.co.jp/site/itemtags/list.aspx?tags=a,b", "tags", None, None),
        ("https://maison.kose.co.jp/site/cosmedecorte/g/gJLCW/", "product", None, "JLCW"),
        ("/site/cosmedecorte/g/gJQBA/", "product", None, "JQBA"),
        ("https://maison.kose.co.jp/site/", None, None, None),
    ]
    for url, route, cat, sku in cases:
        equal("route of %s" % url, product_parser.route_of(url), route)
        equal("category of %s" % url, product_parser.category_from_url(url), cat)
        equal("sku of %s" % url, product_parser.sku_from_url(url), sku)


def check_a_root_relative_href_is_not_mangled():
    """A tile's href is root-relative on a category and absolute on a tag page.

    The first version of `_split` promoted anything without "//" to
    `https://` + the string, which turned "/site/x/g/gJQBA/" into a URL whose
    HOST was "site". Every category row then parsed to sku=None and was
    dropped — 24 tiles in, zero rows out — while `tile_count` reported 24.
    """
    equal("root-relative", product_parser.sku_from_url("/site/x/g/gJQBA/"), "JQBA")
    equal("absolute",
          product_parser.sku_from_url("https://maison.kose.co.jp/site/x/g/gJQBA/"), "JQBA")
    equal("host-relative",
          product_parser.sku_from_url("maison.kose.co.jp/site/x/g/gJQBA/"), "JQBA")


def check_the_brand_segment_is_treated_as_decorative():
    """`/site/xyz/c/c15/` returns byte-identical bytes to the real brand's."""
    a = product_parser.category_from_url("https://maison.kose.co.jp/site/cosmedecorte/c/c15/")
    b = product_parser.category_from_url("https://maison.kose.co.jp/site/xyz/c/c15/")
    equal("the same category either way", (a, b), ("c15", "c15"))
    equal("page 2 of either builds the same address",
          product_parser.page_url("https://maison.kose.co.jp/site/xyz/c/c15/", 2),
          "https://maison.kose.co.jp/site/xyz/c/c15_p2/")
    equal("and the brand slug is recorded as provenance only",
          product_parser.brand_slug_from_url("https://maison.kose.co.jp/site/xyz/c/c15/"),
          "xyz")


def check_both_pagination_conventions():
    cat = "https://maison.kose.co.jp/site/cosmedecorte/c/c15/"
    equal("category page 1 is the bare URL", product_parser.page_url(cat, 1), cat)
    equal("category page 2", product_parser.page_url(cat, 2),
          "https://maison.kose.co.jp/site/cosmedecorte/c/c15_p2/")
    equal("category page 13", product_parser.page_url(cat, 13),
          "https://maison.kose.co.jp/site/cosmedecorte/c/c15_p13/")
    equal("a URL already naming a page is rebuilt, not appended to",
          product_parser.page_url("https://maison.kose.co.jp/site/x/c/c15_p7/", 3),
          "https://maison.kose.co.jp/site/x/c/c15_p3/")
    equal("and normalising it back to page 1 drops the suffix",
          product_parser.page_url("https://maison.kose.co.jp/site/x/c/c15_p7/", 1),
          "https://maison.kose.co.jp/site/x/c/c15/")

    tag = "https://maison.kose.co.jp/site/itemtags/list.aspx?tags=a,b"
    equal("tag page 1 is the bare URL", product_parser.page_url(tag, 1), tag)
    equal("tag page 2 uses ?p=, which is the one the site honours",
          product_parser.page_url(tag, 2),
          "https://maison.kose.co.jp/site/itemtags/list.aspx?tags=a,b&p=2")
    equal("a tag URL already naming a page is replaced, not doubled",
          product_parser.page_url(tag + "&p=4", 2),
          "https://maison.kose.co.jp/site/itemtags/list.aspx?tags=a,b&p=2")
    check("the comma in tags= is NOT percent-encoded, matching the site's own href",
          "%2C" not in product_parser.page_url(tag, 2))

    for n, url in ((1, cat), (7, "https://maison.kose.co.jp/site/x/c/c15_p7/"),
                   (1, tag), (4, tag + "&p=4")):
        equal("page number read back from %s" % url,
              product_parser.page_number_from_url(url), n)


def check_the_wrong_pagination_parameter_is_not_used():
    """`&pageno=` and `&page=` are silently ignored by the site (HTTP 200,
    page 1). A run that built one would dedupe every page down to page 1's
    rows and report a COMPLETE run holding one page."""
    built = product_parser.page_url(
        "https://maison.kose.co.jp/site/itemtags/list.aspx?tags=a,b", 3)
    check("only ?p= is built", "p=3" in built and "pageno" not in built
          and "page=3" not in built, built)


def check_the_sites_own_page_counter_is_read():
    equal("counter on a category page",
          product_parser.total_pages(LISTING_HTML), 13)
    equal("a tag listing publishes none, and None means UNKNOWN",
          product_parser.total_pages(TAGS_HTML), None)
    equal("the separator is the FULLWIDTH solidus, not an ASCII slash",
          product_parser.page_counter("<p>2／13ページ</p>"), (2, 13))
    equal("an ASCII slash is NOT this site's counter and matches nothing",
          product_parser.page_counter("<p>2/13ページ</p>"), (None, None))


def check_pages_are_planned_from_the_counter():
    """Load-bearing here: past its end a category serves its LAST page again.

    Against `page_flow.pages_to_plan`, which is the function the ENGINES
    call. An earlier version of this check exercised a `product_parser`
    helper that the engines had stopped using, so it passed while saying
    nothing about what a run would do (the check #5 found it).
    """
    equal("50 asked, 13 available", list(page_flow.pages_to_plan(50, 13)),
          list(range(1, 14)))
    equal("3 asked, 13 available", list(page_flow.pages_to_plan(3, 13)),
          [1, 2, 3])
    equal("unknown count does not cap the run",
          list(page_flow.pages_to_plan(5, None)), [1, 2, 3, 4, 5])
    equal("and zero available is treated as unknown rather than as a cap",
          list(page_flow.pages_to_plan(5, 0)), [1, 2, 3, 4, 5])
    equal("asking for no pages plans none",
          list(page_flow.pages_to_plan(0, 13)), [])

    # The START page is honoured rather than normalised away. A run pointed
    # at /c/c15_p10/ reads 10, 11, 12 — an earlier version reset every run to
    # page 1, so a run aimed at page 10 quietly returned page 1's products.
    equal("3 asked from page 10", list(page_flow.pages_to_plan(3, 13, 10)),
          [10, 11, 12])
    equal("a run near the end stops at the last page",
          list(page_flow.pages_to_plan(5, 13, 12)), [12, 13])
    equal("a start page past the counter still fetches the page asked for, "
          "because the counter can be stale",
          list(page_flow.pages_to_plan(1, 13, 20)), [20])


def check_listing_page_level_facts():
    lp = product_parser.parse_listing(LISTING_HTML, LISTING_URL, page=1)
    equal("rows", len(lp.rows), 4)
    equal("pages available", lp.pages_available, 13)
    equal("page size", lp.page_size, 24)
    equal("next url", lp.next_url,
          "https://maison.kose.co.jp/site/cosmedecorte/c/c15_p2/")
    equal("canonical", lp.canonical, LISTING_URL)
    equal("tiles counted", lp.tiles_on_page, 4)
    check("product-shaped links outnumber tiles, which is why rows use tiles",
          lp.product_links_on_page > lp.tiles_on_page,
          "%d links vs %d tiles" % (lp.product_links_on_page, lp.tiles_on_page))


def check_supported_urls_are_refused_with_a_true_reason():
    ok, why = product_parser.is_supported_url(LISTING_URL)
    equal("a real listing is supported", (ok, why), (True, "category"))
    for url, needle in [
        ("https://www.kose.co.jp/", "publishes no catalogue"),
        ("https://kose.com/anything", "REFUSED"),
        ("https://kose.com.tw/", "different platform"),
        ("https://example.com/", "is not maison.kose.co.jp"),
        ("https://maison.kose.co.jp/site/", "not a Maison KOSÉ listing"),
    ]:
        ok, why = product_parser.is_supported_url(url)
        check("refused: %s" % url, not ok, why)
        check("...with a reason naming the real problem (%s)" % needle,
              needle.lower() in why.lower(), why)


# ---------------------------------------------------------------------------
# Prices
# ---------------------------------------------------------------------------

def check_price_parsing():
    cases = [
        ("264,000円（税込）", 264000.0),
        ("3,024円（税込/8%）※", 3024.0),
        ("605円（税込）", 605.0),
        ("1,078円", 1078.0),
        ("", None),
        ("価格未定", None),
    ]
    for text, want in cases:
        equal("price of %r" % text, product_parser.parse_price(text), want)


# ---------------------------------------------------------------------------
# Detection. Everything here is a TRIPWIRE: nothing has ever fired on this
# site, and the checks exist so that stays true on purpose rather than by
# accident.
# ---------------------------------------------------------------------------

def check_no_marker_fires_on_a_page_the_site_serves():
    """Count every candidate on a page you KNOW is good, first."""
    good = [("listing", LISTING_HTML), ("tags", TAGS_HTML),
            ("product", PRODUCT_HTML), ("empty", EMPTY_HTML),
            ("404", NOTFOUND_HTML)]
    for name, html in good:
        equal("no challenge detected on the %s fixture" % name,
              product_parser.detect_bot_challenge(html), None)


def check_cf_turnstile_is_not_carried_as_a_marker():
    """2Captcha's own Scraping Browser extension injects `cf-turnstile`
    into every page it loads, so it fires on GOOD pages and misses real
    ones. `challenges.cloudflare.com` is the one that works."""
    markers = [m for m, _ in product_parser.BOT_CHALLENGE_MARKERS]
    check("cf-turnstile is not a marker", "cf-turnstile" not in markers)
    check("challenges.cloudflare.com is", "challenges.cloudflare.com" in markers)
    injected = ('<script src="chrome-extension://kjmkgkdkpedkejedfhmfcenooemhbpbo'
                '/content/captcha/turnstile/hunter.js" '
                'data-ts-input="cf-turnstile-response"></script>')
    page = LISTING_HTML.replace("</head>", injected + "</head>")
    equal("a page carrying the extension's own injection is still clean",
          product_parser.detect_bot_challenge(page), None)


def check_a_marker_would_still_fire_if_the_site_turned_one_on():
    """A tripwire nobody can trip is not a tripwire."""
    page = LISTING_HTML.replace(
        "</head>", '<script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script></head>')
    equal("a real Turnstile is reported", product_parser.detect_bot_challenge(page),
          "cloudflare turnstile")
    equal("and the page state follows the marker rather than the tiles",
          page_flow.classify(page.replace('<li class="c-product__item', '<li class="x'), 200),
          "challenge")


def check_a_marker_survives_both_encodings():
    """An edge can entity-escape the punctuation in its own marker, so a
    literal matches a browser's DOM and misses a raw HTTP response."""
    escaped = ("<html><head><title>Access Denied</title>"
               "<script src=\"https&#58;&#47;&#47;challenges&#46;cloudflare&#46;com"
               "&#47;turnstile&#47;v0&#47;api.js\"></script></head><body></body></html>")
    equal("the escaped spelling is still detected",
          product_parser.detect_bot_challenge(escaped), "cloudflare turnstile")


def check_page_states_on_real_captures():
    equal("a listing is content", page_flow.classify(LISTING_HTML, 200), "content")
    equal("a product page is content too, on its own JSON-LD rather than tiles",
          page_flow.classify(PRODUCT_HTML, 200), "content")
    equal("an exhausted tag facet is EMPTY, not blocked",
          page_flow.classify(EMPTY_HTML, 200), "empty")
    equal("the site's own 404 is empty as well",
          page_flow.classify(NOTFOUND_HTML, 200), "empty")
    equal("a 403 is blocked", page_flow.classify(EMPTY_HTML, 403), "blocked")
    equal("but a 403 on a page that still HAS tiles is content: the tiles are "
          "the stronger signal", page_flow.classify(LISTING_HTML, 403), "content")
    equal("no body at all is unknown", page_flow.classify(None), "unknown")


def check_chromiums_own_error_page_is_not_mistaken_for_the_site():
    """It carries `<title>maison.kose.co.jp</title>` and no vendor marker, so
    only "was this built out of the site's own assets?" answers correctly."""
    equal("no marker matches it",
          product_parser.detect_bot_challenge(CHROMIUM_ERROR_HTML), None)
    equal("it references none of the site's own assets",
          product_parser.references_own_assets(CHROMIUM_ERROR_HTML), 0)
    equal("so it classifies as unknown rather than as an empty listing",
          page_flow.classify(CHROMIUM_ERROR_HTML, 200), "unknown")
    check("while a real page references them repeatedly",
          product_parser.references_own_assets(LISTING_HTML) >= 2,
          str(product_parser.references_own_assets(LISTING_HTML)))


def check_the_unambiguous_signal_is_checked_before_the_threshold():
    """the classification-order trap: a thin but REAL page must not come
    back as blocked because it happens to reference few assets."""
    thin = ('<html><head><script src="/js/sys/cart.js"></script></head><body>'
            '<ul class="c-product-content__list">'
            '<li class="c-product__item"><a href="/site/x/g/gAAAA/">x</a>'
            '<p class="c-product__price">1,000円（税込）</p></li>'
            '</ul></body></html>')
    equal("one asset reference and one real tile is CONTENT",
          page_flow.classify(thin, 200), "content")


def check_the_404_carries_exactly_one_product_link():
    """Which is why the parse-failure threshold is two, not one."""
    equal("the site's 404 links to one product",
          product_parser.product_link_count(NOTFOUND_HTML), 1)
    check("so it is not reported as a broken parser",
          not page_flow.looks_like_a_parse_failure("empty", 0, 1))
    check("while a real grid that parsed to nothing is",
          page_flow.looks_like_a_parse_failure("content", 0, 48))



# ---------------------------------------------------------------------------
# Structural checks the whole family shares.
# ---------------------------------------------------------------------------

def check_shared_calls_bind_against_the_real_signature():
    """the check #1, and the one that earns its keep.

    A sibling repo shipped `classify(html, url=…)` in two of three engines
    against a callee taking `status` second, and BOTH crashed on their first
    fetch — invisible to import, --help, compileall, the undefined-name walk
    and 400+ green assertions, because none of those calls a function the way
    a live run does.

    This walks every engine's AST for calls into the shared modules and binds
    each one against the callee's real signature.
    """
    import page_flow
    import product_parser
    import output_writer
    targets = {"page_flow": page_flow, "product_parser": product_parser,
               "output_writer": output_writer}
    bound = 0
    for module in ENGINES + ("scraper_api_client",):
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        tree = ast.parse(source)
        # Which shared names this file imported directly (`from x import y`).
        direct = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in targets:
                for alias in node.names:
                    direct[alias.asname or alias.name] = (
                        targets[node.module], alias.name)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            owner = attr = None
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
                if func.value.id in targets:
                    owner, attr = targets[func.value.id], func.attr
            elif isinstance(func, ast.Name) and func.id in direct:
                owner, attr = direct[func.id]
            if owner is None:
                continue
            # A name that is NOT THERE is the loudest possible failure and
            # this check used to swallow it: `getattr(..., None)` returned
            # None, `not callable(None)` was true, and the call was skipped.
            # Three calls into a page_flow API that does not exist in this
            # repo -- comparable(), next_page_selector(),
            # next_page_candidates(), all of them Tokopedia's, all arriving
            # with copied code -- sat in two engines under a green run of
            # this very function. Absent is not "nothing to bind".
            if not hasattr(owner, attr):
                check("%s.%s exists (called from %s:%d)"
                      % (getattr(owner, "__name__", owner), attr,
                         module + ".py", node.lineno),
                      False,
                      "the engine calls a name the shared module does not "
                      "define; a live run reaches this as AttributeError")
                continue
            callee = getattr(owner, attr)
            if not callable(callee) or inspect.isclass(callee):
                continue
            try:
                signature = inspect.signature(callee)
            except (TypeError, ValueError):
                continue
            positional = [inspect.Parameter.empty] * len(node.args)
            keywords = {}
            for kw in node.keywords:
                if kw.arg is None:          # **kwargs — cannot be checked here
                    keywords = None
                    break
                keywords[kw.arg] = inspect.Parameter.empty
            if keywords is None:
                continue
            try:
                signature.bind(*positional, **keywords)
                bound += 1
            except TypeError as e:
                check("%s:%d %s.%s(...) binds against its real signature"
                      % (module, node.lineno, owner.__name__, attr),
                      False, "%s; signature is %s" % (e, signature))
    check("every shared-module call in every engine binds (%d checked)" % bound,
          bound > 40, "only %d calls were checked — is the walk finding them?"
          % bound)


def check_credential_scan_is_one_implementation_invoked_from_both():
    """Two sources of truth, one dead and one holed.

    `.github/ci_checks.py` sat in three repos invoked by NOTHING, while
    tests.yml carried an inline grep doing a narrower version of the same job
    — one that matched only ws:// and wss://, so an http://user:pass@
    credential would have sailed past CI.
    """
    script = os.path.join(HERE, ".github", "ci_checks.py")
    check("the credential scan exists as a script", os.path.exists(script))
    if not os.path.exists(script):
        return
    workflow = os.path.join(HERE, ".github", "workflows", "tests.yml")
    if os.path.exists(workflow):
        text = open(workflow, encoding="utf-8").read()
        check("CI INVOKES the script rather than reimplementing it",
              "ci_checks.py" in text)
    result = subprocess.run([sys.executable, script, "--all"], cwd=HERE,
                            capture_output=True, text=True)
    check("the credential scan passes on this repo's own tree",
          result.returncode == 0,
          (result.stdout + result.stderr)[-600:])


def check_ci_calls_the_shared_checks_rather_than_restating_them():
    """One implementation, invoked from both — asserted, not assumed.

    This repo's FIRST CI run failed on exactly this. `tests.yml` carried
    INLINE reimplementations of the `--help` and sample-output checks that
    `.github/ci_checks.py` already implements. The inline sample check still
    imported `output_writer.Business` — a class this repo renamed to
    `Product` — so the job died with ImportError while `ci_checks.py` passed
    on the same tree. One copy had been updated and the other had not, and
    nothing in the repo could see the difference.

    The guard triggers on the whole `.github` directory being absent, never
    on a file inside it being missing: two suites in this family run
    INSIDE the Docker image, which deliberately COPYs no `.github/`, so a
    check that reads a workflow file is correct in the repo and red in the
    image. A check that quietly starts passing once its input disappears is
    the failure mode this one is guarding against, so the escape is the
    directory, not the file.
    """
    github_dir = os.path.join(HERE, ".github")
    if not os.path.isdir(github_dir):
        skip("ci wiring", "no .github/ directory (this is the Docker image, "
                          "which deliberately carries no CI material)")
        return

    workflow = os.path.join(github_dir, "workflows", "tests.yml")
    script = os.path.join(github_dir, "ci_checks.py")
    check("ci_checks.py exists", os.path.exists(script))
    check("tests.yml exists", os.path.exists(workflow))
    if not (os.path.exists(workflow) and os.path.exists(script)):
        return

    text = open(workflow, encoding="utf-8").read()
    for flag in ("--help-check", "--sample-check", "--secret-check"):
        check("tests.yml invokes ci_checks.py %s" % flag,
              "ci_checks.py" in text and flag in text,
              "the workflow must CALL the shared check, not restate it")

    # The positive direction is not enough on its own: the workflow could
    # call the script AND still carry a stale inline copy beside it, which is
    # exactly the state that broke the first run. So assert the tell-tales of
    # a reimplementation are gone.
    # Deliberately NOT keyed on the filename. `sample_output.json` appears
    # legitimately in the docker job, which asserts the IMAGE does not carry
    # it — so a filename tell-tale fails on a correct workflow, which is its
    # own kind of check nobody can read. What actually distinguishes a
    # reimplementation is inline Python that imports the row model or
    # dataclass machinery to rebuild the expected column list.
    for tell in ("from output_writer import", "asdict("):
        check("tests.yml does not reimplement the sample check (%r)" % tell,
              tell not in text,
              "an inline copy drifts from the shared one silently")


def check_banned_wording():
    """Enforced by this test rather than by review."""
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "__pycache__", ".pytest_cache", "node_modules")]
        for filename in files:
            if not filename.endswith((".py", ".md", ".yml", ".yaml", ".txt",
                                      ".toml", ".html", ".example")):
                continue
            path = os.path.join(root, filename)
            text = open(path, encoding="utf-8", errors="replace").read().lower()
            for phrase in BANNED_WORDING:
                if phrase.lower() in text and filename != "smoke_test.py":
                    check("%s contains no %r" % (
                        os.path.relpath(path, HERE), phrase), False)
    check("banned-wording scan ran", True)


# The project's notes outside this repository are private: a pointer to them
# is a dead reference for every reader. Assembled from pieces so this file
# can be scanned too.
PRIVATE_CITATIONS = (
    "CLAUDE" + ".md",
    "claude_" + "2scraper",
    "2scraper_" + "repo_rules",
    "play" + "book",
    "template " + "\u00a7",
    "\u00a7",                  # a bare section sign: a numbered private rule
)


def check_no_citations_of_private_notes():
    """Shipped files state each rule in their own words.

    They used to cite a private file by name and by section number — in the
    README, in `--help` output, in docstrings and in release notes — which
    reads as a pointer into a document no reader can open.
    """
    names = (".gitignore", ".dockerignore", "Dockerfile", ".env.example")
    scanned = 0
    for root, dirs, files in os.walk(HERE):
        dirs[:] = [d for d in dirs
                   if d not in (".git", "__pycache__", ".pytest_cache",
                                "node_modules")
                   and not os.path.exists(os.path.join(root, d, "pyvenv.cfg"))]
        for filename in files:
            if not (filename.endswith((".py", ".md", ".yml", ".yaml", ".txt",
                                       ".toml", ".cfg", ".html", ".example"))
                    or filename in names):
                continue
            path = os.path.join(root, filename)
            text = open(path, encoding="utf-8", errors="replace").read()
            scanned += 1
            for token in PRIVATE_CITATIONS:
                if token.lower() in text.lower():
                    line = next(i for i, l in enumerate(text.splitlines(), 1)
                                if token.lower() in l.lower())
                    check("%s:%d cites private notes (%r)" % (
                        os.path.relpath(path, HERE), line, token), False)
    check("the private-citation scan read files", scanned > 10, str(scanned))


def check_worker_pools_start_on_different_exits():
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    from proxy_pool import ProxyPool
    pool = ProxyPool(["http://a:1", "http://b:2", "http://c:3"], rotate="per-run")
    firsts = [engine._worker_pool(pool, i).current for i in range(3)]
    equal("three workers start on three different exits",
          len(set(firsts)), 3)
    equal("a missing pool stays missing", engine._worker_pool(None, 0), None)


def check_fingerprint_kwargs_are_ones_the_driver_accepts():
    """An unknown key in new_context(**kwargs) is a TypeError at launch,
    on the PAID path, at runtime."""
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return
    try:
        from fingerprint_client import playwright_context_kwargs
    except ImportError as e:
        skip("fingerprint", str(e))
        return
    sample = {"id": "x", "country": "US",
              "userAgent": "Mozilla/5.0 Chrome/140.0.0.0",
              "screen": {"width": 1920, "height": 1080},
              "timezone": "America/New_York", "language": "en-US",
              "devicePixelRatio": 2}
    kwargs = playwright_context_kwargs(sample)
    from playwright.sync_api import sync_playwright  # noqa: F401
    import playwright.sync_api as pw_api
    signature = inspect.signature(pw_api.Browser.new_context)
    unknown = [k for k in kwargs if k not in signature.parameters]
    check("every fingerprint kwarg is one new_context accepts", not unknown,
          "unknown: %s" % unknown)


def check_engines_do_not_evaluate_a_string_in_the_browser():
    """A site whose CSP omits `unsafe-eval` kills wait_for_function with
    an EvalError and takes the run down with exit 1. Maison KOSÉ has not been
    measured for that, and the cheap habit costs nothing where it would have
    been allowed."""
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        called = {node.func.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Call)
                  and isinstance(node.func, ast.Attribute)}
        for banned in ("wait_for_function", "waitForFunction", "waitFor"):
            check("%s never CALLS %s" % (module, banned), banned not in called,
                  "poll through page_flow.wait_for_count instead")


def check_credentials_never_reach_a_log():
    """An EXCEPTION MESSAGE is a log, and the masker must be GLOBAL.

    A Playwright connection error repeats the endpoint five times (the
    message plus a four-line call log), so a masker handling only the first
    occurrence prints the password four times and looks like it is working.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        masked = engine._mask_credentials(
            "tried ws://u:supersecret@h1:9222 and ws://u:supersecret@h2:9222 "
            "and again ws://u:supersecret@h1:9222")
        check("%s masks EVERY occurrence" % module,
              "supersecret" not in masked, masked)
        check("%s keeps the host and port, which are the useful half" % module,
              "h1:9222" in masked and "h2:9222" in masked, masked)
    from proxy_pool import mask
    masked = mask("http://user:secret@exit.example.com:2334")
    check("proxy_pool.mask hides the password", "secret" not in masked)
    check("proxy_pool.mask keeps the exit", "exit.example.com:2334" in masked)


def check_csv_and_json_writers():
    from output_writer import Product, write_csv, write_json
    import product_parser as P
    rows = P.parse_listing(LISTING_HTML, LISTING_URL).rows
    check("the fixture produced rows to write", len(rows) > 0, len(rows))
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "out.csv")
        write_csv(rows, csv_path, row_cls=Product)
        with open(csv_path, encoding="utf-8") as f:
            reader = list(csv.reader(f))
        equal("CSV header matches the dataclass, in order",
              reader[0], [f.name for f in fields(Product)])
        equal("CSV holds every row", len(reader) - 1, len(rows))
        check("no Python list repr leaked into the CSV",
              not any(cell.startswith("[") for row in reader[1:] for cell in row))

        empty_csv = os.path.join(tmp, "empty.csv")
        write_csv([], empty_csv, row_cls=Product)
        with open(empty_csv, encoding="utf-8") as f:
            header = list(csv.reader(f))
        equal("an EMPTY csv still carries its header", len(header), 1)
        equal("...and it is the right one", header[0],
              [f.name for f in fields(Product)])

        json_path = os.path.join(tmp, "out.json")
        write_json(rows, json_path)
        loaded = json.load(open(json_path, encoding="utf-8"))
        equal("JSON holds every row", len(loaded), len(rows))
        equal("JSON keys are the dataclass fields, in order",
              list(loaded[0].keys()), [f.name for f in fields(Product)])
        equal("JSON and CSV agree on the column ORDER",
              list(loaded[0].keys()), reader[0])


def check_exit_codes():
    import output_writer as O
    equal("0 ok / 1 crash / 2 usage / 3 blocked / 4 empty / 5 api / 6 partial",
          (O.EXIT_BLOCKED, O.EXIT_NO_PRODUCTS, O.EXIT_API_ERROR, O.EXIT_PARTIAL),
          (3, 4, 5, 6))
    check("page_cap_reached is a COMPLETE stop reason",
          "page_cap_reached" in O.COMPLETE_STOP_REASONS)
    check("single_page_mode is complete by construction",
          "single_page_mode" in O.COMPLETE_STOP_REASONS)
    check("no_new_products is complete",
          "no_new_products" in O.COMPLETE_STOP_REASONS)


def check_a_run_that_finds_nothing_writes_nothing():
    """Never replace last night's good output with []."""
    from output_writer import save
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "out")
        with open(prefix + ".json", "w", encoding="utf-8") as f:
            f.write('[{"sku": "yesterday"}]')
        code = save([], prefix, "json", allow_empty=False)
        equal("an empty run exits 4", code, 4)
        equal("...and leaves the previous good file alone",
              open(prefix + ".json", encoding="utf-8").read(),
              '[{"sku": "yesterday"}]')
        code = save([], prefix, "json", allow_empty=True)
        equal("--allow-empty WRITES the empty file...", 
              json.load(open(prefix + ".json", encoding="utf-8")), [])
        # ...and still reports exit 4. Pinned deliberately (pin a known
        # behaviour rather than half-guarding it): "zero products" is true
        # whether or not the file was written, and a caller that wanted the
        # file still wants to know the result was empty.
        equal("...and still reports exit 4, because it IS empty", code, 4)


def check_concurrency_with_the_browser_stubbed():
    """A live run cannot always reach this machinery.

    Page 1 is fetched alone and decides how many pages there are, so a
    blocked page 1 means the workers never start. Driven directly instead,
    with the browser replaced.
    """
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return

    class Args:
        delay = 0
        retries = 1
        retry_delay = 0
        out = "unused"
        mode = "search"
        sort = "a-z"
        pages = 50

    fetched = []
    import threading
    lock = threading.Lock()

    def fake_fetch(session, args, pool, page_num, url):
        with lock:
            fetched.append(page_num)
        outcome = engine.PageOutcome(page_num=page_num, url=url)
        # Page 6 is the end of this listing: no rows, but a served page.
        outcome.products = [] if page_num >= 6 else [object()] * 15
        outcome.state = "empty" if page_num >= 6 else "content"
        return outcome

    class FakeSession:
        def __init__(self, *a, **k):
            self.pool = None
        def open(self):
            return self
        def close(self):
            pass

    class FakePlaywright:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    real_fetch = engine._fetch_one_page
    real_session = engine._BrowserSession
    real_pw = engine.sync_playwright
    engine._fetch_one_page = fake_fetch
    engine._BrowserSession = FakeSession
    engine.sync_playwright = lambda: FakePlaywright()
    try:
        specs = [(n, "u%d" % n) for n in range(2, 51)]
        results, unattempted, exhausted = engine._fetch_pages_concurrently(
            Args(), None, specs, 4)
    finally:
        engine._fetch_one_page = real_fetch
        engine._BrowserSession = real_session
        engine.sync_playwright = real_pw

    check("every page fetched was fetched exactly once",
          len(fetched) == len(set(fetched)), "%r" % sorted(fetched))
    check("dispatch STOPPED at the end of the listing", exhausted)
    check("...so the 49 queued pages cost far fewer fetches",
          len(fetched) < 15, "fetched %d of 49" % len(fetched))
    check("unattempted pages are REPORTED, not counted as failed",
          len(unattempted) > 0 and all(isinstance(n, int) for n in unattempted))
    equal("attempted + unattempted covers the whole queue",
          len(set(fetched)) + len(unattempted), 49)
    equal("outcomes are restorable to page order",
          [o.page_num for o in sorted(results, key=lambda o: o.page_num)],
          sorted(o.page_num for o in results))


def check_a_dead_worker_neither_hangs_nor_loses_its_siblings():
    engine = _import_engine("playwright_scraper")
    if engine is None:
        return

    class Args:
        delay = 0
        retries = 1
        retry_delay = 0
        out = "unused"
        mode = "search"
        sort = "a-z"
        pages = 10

    def exploding_fetch(session, args, pool, page_num, url):
        if page_num == 3:
            raise RuntimeError("worker died")
        outcome = engine.PageOutcome(page_num=page_num, url=url)
        outcome.products = [object()] * 15
        outcome.state = "content"
        return outcome

    class FakeSession:
        def __init__(self, *a, **k):
            self.pool = None
        def open(self):
            return self
        def close(self):
            pass

    class FakePlaywright:
        def __enter__(self):
            return None
        def __exit__(self, *a):
            return False

    real_fetch, real_session, real_pw = (engine._fetch_one_page,
                                         engine._BrowserSession,
                                         engine.sync_playwright)
    engine._fetch_one_page = exploding_fetch
    engine._BrowserSession = FakeSession
    engine.sync_playwright = lambda: FakePlaywright()
    try:
        specs = [(n, "u%d" % n) for n in range(2, 8)]
        results, unattempted, exhausted = engine._fetch_pages_concurrently(
            Args(), None, specs, 3)
    finally:
        engine._fetch_one_page = real_fetch
        engine._BrowserSession = real_session
        engine.sync_playwright = real_pw

    check("the run returned rather than hanging", True)
    check("the dead worker's siblings still delivered their pages",
          len(results) >= 3, "%d results" % len(results))
    check("page 3 is not reported as a success",
          3 not in [o.page_num for o in results])


def check_no_statement_is_unreachable():
    """A statement sitting after a return/raise/break/continue in the SAME
    block, which therefore can never run.

    Narrow on purpose: it makes no claim about reachability in general, only
    about a block whose control flow has already left. Measured across the
    eighteen repos of this family on 2026-09-16 it reported six problems and
    zero false positives.

    `check_undefined_names_in_every_module` cannot see this class at all, by
    design -- it pools every binding in the file rather than tracking scopes,
    so a name used inside dead code passes as long as anything else in the
    module binds it. What was hiding in that blind spot here, and in five
    sibling repos, byte for byte: a function whose `def` line had been lost,
    leaving its docstring and body absorbed into the end of the function
    above it. Present since this repo's first commit, invisible to import,
    `--help`, `compileall`, and every green run of this suite.
    """
    for filename in sorted(f for f in os.listdir(HERE) if f.endswith(".py")):
        tree = ast.parse(open(os.path.join(HERE, filename),
                              encoding="utf-8").read())
        dead = []
        for node in ast.walk(tree):
            for field in ("body", "orelse", "finalbody"):
                block = getattr(node, field, None)
                if not isinstance(block, list):
                    continue
                for i, stmt in enumerate(block[:-1]):
                    if isinstance(stmt, (ast.Return, ast.Raise,
                                         ast.Continue, ast.Break)):
                        dead.append(block[i + 1].lineno)
                        break
        check("%s: no statement the control flow can never reach" % filename,
              not dead, "first at line %d" % min(dead) if dead else "")


def check_undefined_names_in_every_module():
    """Compileall proves a file PARSES, not that its names RESOLVE.

    A live run of a sibling repo's pyppeteer engine died with NameError on a
    line reached only while fetching, after an import had been removed — the
    module imported cleanly, --help worked, compileall passed and CI was
    green. Kept COARSE (pooled bindings, no scope tracking) so it
    under-reports rather than inventing problems.
    """
    import builtins
    modules = [f for f in sorted(os.listdir(HERE))
               if f.endswith(".py") and f != "smoke_test.py"]
    for filename in modules:
        tree = ast.parse(open(os.path.join(HERE, filename), encoding="utf-8").read())
        # Module-level dunders exist without being assigned anywhere.
        defined = set(dir(builtins)) | {"__file__", "__name__", "__doc__",
                                        "__package__", "__spec__"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    defined.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                   ast.ClassDef)):
                defined.add(node.name)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                defined.add(node.id)
            elif isinstance(node, ast.arg):
                defined.add(node.arg)
            elif isinstance(node, ast.ExceptHandler) and node.name:
                defined.add(node.name)
            elif isinstance(node, ast.alias) and node.asname:
                defined.add(node.asname)
        used = {n.id for n in ast.walk(tree)
                if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        unresolved = sorted(used - defined)
        check("%s: every name resolves" % filename, not unresolved,
              "%s" % unresolved)


def check_dockerfile_copies_everything_the_entrypoint_imports():
    """All three repos in this family shipped an image that died with
    ModuleNotFoundError on every invocation, --help included, because
    proxy_pool.py was missing from the COPY list. CI never built the image;
    this check needs no Docker."""
    path = os.path.join(HERE, "Dockerfile")
    if not os.path.exists(path):
        check("Dockerfile exists", False)
        return
    dockerfile = open(path, encoding="utf-8").read()
    # Only the COPY instructions, continuations included — a comment above
    # them naming a file is not a file the image carries.
    copy_lines, joining = [], False
    for line in dockerfile.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if joining or stripped.upper().startswith("COPY "):
            copy_lines.append(stripped)
            joining = stripped.endswith("\\")
    copied = set(re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\.py", " ".join(copy_lines)))
    entry = re.search(r'(?:CMD|ENTRYPOINT)\s*\[?\s*"?(?:python3?"?,\s*"?)?'
                      r'([A-Za-z_][A-Za-z0-9_]*)\.py', dockerfile)
    entrypoint = entry.group(1) if entry else "playwright_scraper"
    needed = _import_graph(entrypoint)
    missing = sorted(needed - copied)
    check("the Dockerfile COPYs every module %s.py imports" % entrypoint,
          not missing, "missing %s" % missing)
    for unwanted in ("smoke_test", "test_smoke"):
        check("the image does not carry %s.py" % unwanted,
              unwanted not in copied)


def check_env_example_documents_exactly_what_the_loader_reads():
    import env_config
    path = os.path.join(HERE, ".env.example")
    if not os.path.exists(path):
        check(".env.example exists", False)
        return
    documented = set(re.findall(r"^\s*#?\s*([A-Z][A-Z0-9_]+)\s*=", 
                                open(path, encoding="utf-8").read(), re.M))
    read = set(env_config.ENV_KEYS)
    check("every variable the loader reads is documented",
          not (read - documented), "undocumented: %s" % sorted(read - documented))
    check("every documented variable is actually read",
          not (documented - read), "unread: %s" % sorted(documented - read))


def check_a_copied_env_example_reads_as_UNSET():
    """`cp .env.example .env` followed by a run must not connect.

    The placeholder check was a literal set in a sibling repo, and the two
    credentialled URLs are documented the way the vendor documents them —
    `ws://{login}-zone-…:{password}@cb.2captcha.com:9222` — so neither
    literal matched, the run connected with the string `{login}-zone-…` as
    its username, and got a 401 a long way from its cause.
    """
    import env_config
    example = os.path.join(HERE, ".env.example")
    if not os.path.exists(example):
        check(".env.example exists", False)
        return
    text = open(example, encoding="utf-8").read()
    # KOSE_URL is shipped COMMENTED OUT: a copied .env that set it made
    # every run without --url fetch that address, and the --tags/--category
    # builders then had to work around a URL nobody typed. It is still
    # documented, so it is still read from the commented line here.
    check("KOSE_URL is shipped commented out",
          re.search(r"^#\s*KOSE_URL=", text, re.M) is not None
          and re.search(r"^KOSE_URL=", text, re.M) is None)
    values = dict(re.findall(r"^(?:#\s*(?=KOSE_URL=))?([A-Z][A-Z0-9_]+)=(.*)$",
                             text, re.M))
    check("the example actually sets every variable",
          set(values) == set(env_config.ENV_KEYS),
          "example has %s, loader reads %s"
          % (sorted(values), sorted(env_config.ENV_KEYS)))
    # Every CREDENTIAL must read as unset. The default TARGET must not: it is
    # a real, usable URL, and blanking it would remove the one setting this
    # file exists to make convenient (the check #3 says exactly this — the
    # credentials unset, the non-credential default still usable).
    CREDENTIALS = {"TWOCAPTCHA_KEY", "KOSE_CDP_ENDPOINT", "KOSE_PROXY"}
    before = dict(os.environ)
    try:
        for name, raw in values.items():
            os.environ[name] = raw
            got = env_config.env_value(name)
            if name in CREDENTIALS:
                check("a copied .env.example leaves %s unset" % name,
                      got is None, "got %r" % got)
            else:
                check("...while %s stays a usable default" % name,
                      got == raw.strip(), "got %r" % got)
    finally:
        os.environ.clear()
        os.environ.update(before)
    # And the counter-check: a real credential must still come through, or
    # the placeholder rule would have made the loader useless. Deliberately
    # NOT 32 hex characters — that is the shape of a real 2captcha key, and
    # this repo's own credential scan (rightly) fails on one.
    try:
        os.environ["TWOCAPTCHA_KEY"] = "not-a-real-key-but-a-real-value"
        equal("a real value is still read",
              env_config.env_value("TWOCAPTCHA_KEY"),
              "not-a-real-key-but-a-real-value")
    finally:
        os.environ.clear()
        os.environ.update(before)


def check_engines_import_their_driver_at_module_level():
    """For the guarded imports above to MEAN anything.

    A sibling repo imported `launch`/`connect` inside the launch path, so the
    module imported cleanly with no pyppeteer installed: the group never
    skipped, and the CI job that exists to fail on unexpected skips could not
    have caught a broken import. It also let CI run against a stub version
    for a while without anything noticing. This drifts back silently, so it
    is asserted with an `ast` walk rather than trusted.
    """
    for module, driver in DRIVER_IMPORTS.items():
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            check("%s exists" % module, False)
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        top_level = set()
        for node in tree.body:          # module level ONLY
            if isinstance(node, ast.Import):
                top_level.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.add(node.module.split(".")[0])
        check("%s imports %s at MODULE level" % (module, driver),
              driver in top_level,
              "top-level imports: %s" % sorted(top_level))


def check_engine_flag_sets():
    """the check #2: against the contract AND against each other, both ways.

    A missing flag fails; so does closing a difference the README documents.
    """
    sets = {}
    for module in ENGINES:
        if not os.path.exists(os.path.join(HERE, module + ".py")):
            continue
        sets[module] = _argparse_flags(module)
    for module, flags in sets.items():
        missing = (CONTRACT_FLAGS | EXTRA_FLAGS) - flags
        check("%s defines every contract flag" % module, not missing,
              "missing %s" % sorted(missing))
    # The ONE documented difference: pyppeteer downloads its own Chromium
    # and could not launch it on the development machine, so it needs a way
    # to point at another one. Its twins have no equivalent because they do
    # not ship a browser. Listed here so that closing the difference — or
    # growing a second one — fails the build.
    DOCUMENTED_DIFFERENCES = {"puppeteer_scraper": {"--chromium-path"}}
    names = sorted(sets)
    for i in range(len(names) - 1):
        a, b = names[i], names[i + 1]
        only_a = sets[a] - sets[b] - DOCUMENTED_DIFFERENCES.get(a, set())
        only_b = sets[b] - sets[a] - DOCUMENTED_DIFFERENCES.get(b, set())
        check("%s and %s define the same flags" % (a, b),
              not only_a and not only_b,
              "only in %s: %s; only in %s: %s"
              % (a, sorted(only_a), b, sorted(only_b)))


def check_banned_and_removed_flags():
    """Scoped to the ENGINES.

    `--country` is absent here — the flag this project bans outright on a scraper,
    because it could disagree with the URL. `--locale` is absent too:
    maison.kose.co.jp is one market (see EXTRA_FLAGS above).

    The same reasoning applies to the flags this repo DOES have: `--tags`
    and `--category` each build an address, so a `--tags` given alongside
    `--url` is refused rather than merged, and `--category` takes only a
    cNN id. This check pins both refusals in every engine.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        for flag in BANNED_FLAGS:
            check("%s does not define %s" % (module, flag),
                  '"%s"' % flag not in source)
        check("%s does not define the banned --country" % module,
              '"--country"' not in source,
              "banned: it could disagree with the URL")
        check("%s refuses --tags alongside --url" % module,
              "--url already names what to fetch" in source,
              "two ways to say what to fetch must not be merged in silence")
        check("%s builds a category URL only from a cNN id" % module,
              "--category builds a URL from a category id" in source,
              "the brand slug selects nothing on this site, so a flag taking "
              "one would build an address whose meaning it does not control")


def check_every_engine_exposes_the_same_public_surface():
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        for name in ("scrape", "parse_args", "PageOutcome", "_fetch_one_page",
                     "_parse_for_mode", "_target_url"):
            check("%s.%s exists" % (module, name), hasattr(engine, name))
        outcome = engine.PageOutcome(page_num=1, url="u")
        for field_name in ("state", "canonical", "pages_available",
                           "products", "blocked_by",
                           "load_failed", "final_url"):
            check("%s.PageOutcome carries %r" % (module, field_name),
                  hasattr(outcome, field_name))
        check("%s.PageOutcome.ok is True for a fresh outcome" % module,
              outcome.ok)
        equal("%s shares CORE_FIELDS with its twins" % module,
              tuple(engine.CORE_FIELDS),
              ("title", "url", "sku", "brand", "currency"))
        equal("%s shares PRICE_COVERAGE_FLOOR with its twins" % module,
              engine.PRICE_COVERAGE_FLOOR, 95)
        equal("%s shares CORE_FIELD_FLOOR with its twins" % module,
              engine.CORE_FIELD_FLOOR, 99)


def check_sample_output_matches_the_schema():
    from output_writer import Product
    expected = [f.name for f in fields(Product)]
    json_path = os.path.join(HERE, "sample_output.json")
    csv_path = os.path.join(HERE, "sample_output.csv")
    if not os.path.exists(json_path):
        check("sample_output.json exists", False)
        return
    rows = json.load(open(json_path, encoding="utf-8"))
    check("sample_output.json holds rows", bool(rows))
    equal("sample_output.json keys match the schema, in order",
          list(rows[0].keys()), expected)
    check("sample_output.json is from a real run (maison.kose.co.jp rows)",
          all(r["source"] == "maison.kose.co.jp" for r in rows))
    check("...and every row carries a tax rate beside its price",
          all(r.get("tax_rate") for r in rows if r.get("price") is not None),
          "a tax-inclusive price with no rate cannot be converted back")
    check("...and the sample shows BOTH tax rates, so the reduced one is "
          "visible to anyone reading the file rather than only the code",
          {r.get("tax_rate") for r in rows} == {8, 10},
          str(sorted({r.get("tax_rate") for r in rows})))
    check("...and both modes, so a reader sees which columns each populates",
          {r.get("mode") for r in rows} == {"listing", "product"},
          str(sorted({r.get("mode") for r in rows})))
    check("...and a row of each stock state",
          {r.get("in_stock") for r in rows} >= {True, False},
          str(sorted(str(r.get("in_stock")) for r in rows)))
    check("...and a currency wherever there is a price",
          all(r.get("currency") for r in rows if r.get("price") is not None))
    check("...and carries no fabrication markers",
          not any("example" in (r.get("url") or "").lower() or
                  "lorem" in (r.get("title") or "").lower() for r in rows))
    if os.path.exists(csv_path):
        header = next(csv.reader(open(csv_path, encoding="utf-8")))
        equal("sample_output.csv header matches the schema", header, expected)


def check_no_test_mutates_the_working_tree():
    """One suite used its own file as a fake chromedriver and chmod'd it
    to 755, leaving a mode change in git status.

    Compares the tree against how it looked when the suite STARTED, not
    against a clean checkout — otherwise this is permanently red while
    anyone is editing, and a check that is always red teaches everyone to
    ignore checks.
    """
    if _TREE_BEFORE is None:
        skip("git status", "not a git repository")
        return
    after = _tree_state()
    changed = sorted(set(after) - set(_TREE_BEFORE))
    check("the suite itself changed nothing in the working tree",
          not changed, "%s" % changed)


def check_captcha_capability_claims_match_the_code():
    """The most expensive bug this family can ship is a SENTENCE.

    It fails in both directions and this family has shipped both:

      * saying a captcha CANNOT be solved, when the true statement is that
        THIS REPO does not implement the task type. 2Captcha solves
        enterprise reCAPTCHA and Cloudflare Turnstile and has for years, so
        such a sentence tells a reader not to buy something that works.
      * saying this repo DOES solve something it builds no task type for --
        which is what the README said here: it billed the Managed Challenge
        solve to `--twocaptcha-key`, while the only thing that clears one is
        `Captcha.setAutoSolve` over `--cdp-endpoint`.

    Neither is visible to any other check: nothing fails, nothing crashes,
    and the output is correct.
    """
    readme = open(os.path.join(HERE, "README.md"), encoding="utf-8").read()
    solver = open(os.path.join(HERE, "captcha_solver.py"), encoding="utf-8").read()
    low = readme.lower()

    # Conclusions about the PRODUCT. "Unsolvable" is a property of a PAGE —
    # it means the page carries no widget — and never of a vendor. 2Captcha
    # solves enterprise reCAPTCHA and Cloudflare Turnstile and has for years,
    # so a sentence saying otherwise tells a reader not to buy something that
    # works, and nothing else in this suite can see it.
    for phrase in ("cannot be solved", "can't be solved", "neither is solvable",
                   "is not solvable", "solver is inapplicable", "no solver can",
                   "2captcha cannot", "no captcha service"):
        check("README: no %r -- write 'this repo does not implement X'" % phrase,
              phrase not in low)

    # The pairing that matters ON THIS SITE.
    #
    # The sibling repo pins "the README must say TurnstileTaskProxyless is
    # not built here", because that site renders Cloudflare Managed
    # Challenges and a reader could reasonably expect a key to clear one.
    # Maison KOSÉ renders NO challenge at all, so the equivalent hazard is the opposite one: this
    # README's central claim is that no key is needed, and a claim like that
    # rots the moment the site switches a bot manager on.
    #
    # So the claim has to be PAIRED with the thing that would retest it — the
    # scheduled canary — rather than left as a sentence nobody re-measures.
    claims_no_key = ("no, and it would be dishonest" in low
                     or "do i need a 2captcha account" in low)
    if claims_no_key:
        check("README pairs 'no key needed' with the canary that retests it",
              "canary" in low,
              "a claim that the site is ungated goes stale silently; the "
              "scheduled canary is what turns it back into a measurement")
        check("...and dates the measurement it rests on",
              re.search(r"20\d\d-\d\d-\d\d", readme) is not None,
              "a number describing a living thing needs its moment")

    # And in the other direction: if the README names a task type, the solver
    # had better build it. A capability claim citing no task type is a guess
    # wearing a fact's clothes; one citing a task type nobody implemented is
    # worse.
    for task in ("TurnstileTaskProxyless", "RecaptchaV2EnterpriseTaskProxyless",
                 "RecaptchaV3TaskProxyless"):
        if task.lower() in low:
            check("README names %s, so the solver must build it" % task,
                  task in solver,
                  "the README credits a task type this repo does not send")

    # Whatever the README credits with clearing the challenge must be a thing
    # the engines actually do.
    if "setautosolve" in low:
        srcs = ""
        for name in ("playwright_scraper.py", "selenium_scraper.py",
                     "puppeteer_scraper.py"):
            path = os.path.join(HERE, name)
            if os.path.exists(path):
                srcs += open(path, encoding="utf-8").read()
        check("README credits Captcha.setAutoSolve, and an engine calls it",
              "Captcha.setAutoSolve" in srcs)


def check_policy_constants_have_a_consumer():
    """A policy constant nothing reads is the same defect as dead code.

    `RETRY_ON_BLOCKED` carried a paragraph of measured justification in a
    sibling repo and NO engine consulted it, so setting it False changed
    nothing while the prose read like enforcement.
    """
    import page_flow
    sources = {}
    for name in ("playwright_scraper", "puppeteer_scraper", "selenium_scraper"):
        path = os.path.join(HERE, name + ".py")
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                sources[name] = f.read()
    check("policy: the engines are readable", len(sources) == 3, sorted(sources))

    for const in ("RETRY_ON_BLOCKED", "BLOCK_RETRIES_WITHOUT_POOL",
                  "SOLVES_PER_PAGE"):
        readers = [n for n, s in sources.items() if const in s]
        check("policy: %s is read by an engine" % const, readers, "no consumer")


def check_state_policy():
    import page_flow

    equal("policy: content is parsed", page_flow.should_parse("content"), True)
    equal("policy: content is not retried", page_flow.should_retry("content"), False)

    # An empty page is an ANSWER. It must not be retried and must not be
    # reported as blocked.
    equal("policy: empty is parsed", page_flow.should_parse("empty"), True)
    equal("policy: empty is not retried", page_flow.should_retry("empty"), False)
    equal("policy: empty is not blocked", page_flow.counts_as_blocked("empty"), False)

    # A refusal offers nothing to solve, so it must not spend money.
    equal("policy: blocked never pays a solver",
          page_flow.should_solve("blocked"), False)
    equal("policy: blocked is blocked", page_flow.counts_as_blocked("blocked"), True)

    # A rendered widget IS a test, and is the one state that pays.
    equal("policy: a captcha may be solved", page_flow.should_solve("challenge"), True)

    equal("policy: unknown waits rather than spending",
          (page_flow.should_retry("unknown"), page_flow.should_solve("unknown")),
          (True, False))
    # An unrecognised state must fall back to the cautious one rather than
    # raising, so a new state name cannot crash a run mid-flight.
    equal("policy: an unknown state name falls back to 'unknown'",
          page_flow.should_solve("something-new"), False)


def check_pagination_addressability_is_asked_per_url():
    import page_flow
    check("pagination: a category listing is addressable",
          page_flow.pagination_is_addressable(LISTING_URL))
    check("pagination: a tag listing is addressable too — both routes were "
          "CHECKED against the site's own rel=next before being trusted",
          page_flow.pagination_is_addressable(TAGS_URL))
    check("pagination: a PRODUCT page is not — it is one page",
          not page_flow.pagination_is_addressable(PRODUCT_URL))


def check_page_and_position_are_unique_across_pages():
    """One line, and the column is worthless without it: `position` restarts
    at 1 on every page."""
    import product_parser as P
    page1 = P.parse_listing(LISTING_HTML, LISTING_URL, page=1).rows
    page2 = P.parse_listing(LISTING_HTML, LISTING_URL, page=2).rows
    pairs = [(r.page, r.position) for r in page1 + page2]
    equal("page+position is unique across a multi-page run",
          len(set(pairs)), len(pairs))
    equal("page 2's rows really say page 2",
          sorted({r.page for r in page2}), [2])


def check_a_broken_parser_is_not_reported_as_an_empty_category():
    """A served page that links to N products and parses to zero is OUR
    bug, and saying "0 products" sends the reader to check the URL instead.

    It is also worth checking the signal CAN fire before adding it. Here it
    genuinely can, and the margin is measured: rows come from
    `li.c-product__item` tiles while `product_link_count` counts `/g/g…/`
    hrefs, and a real grid page carries 48-55 of the latter against 24 of the
    former. So a tile-markup change leaves every link in place and takes
    every row away — which is what this fixture simulates.
    """
    import page_flow
    from product_parser import product_link_count, parse_products, detect_page_state

    # Built by breaking the ELEMENT of every tile while leaving its links,
    # its prices and the site's own assets untouched — which is exactly the
    # shape a markup change takes, and the shape that makes rows vanish while
    # `product_link_count` carries on reporting a healthy page.
    broken = LISTING_HTML.replace('<li class="c-product__item',
                                  '<div class="c-product__item')
    links = product_link_count(broken)
    check("parse-failure: the fixture still links to products", links >= 4, str(links))
    equal("parse-failure: and parses to nothing",
          len(parse_products(broken, LISTING_URL)), 0)
    equal("parse-failure: while the page reads as served",
          detect_page_state(broken, 200, "")[0], "empty")

    check("parse-failure: that combination is flagged",
          page_flow.looks_like_a_parse_failure("empty", 0, links))

    # A genuinely empty category must NOT be flagged — that is a correct
    # answer, and crying wolf on it is the failure this guards against.
    equal("parse-failure: an empty category with no product links is not one",
          page_flow.looks_like_a_parse_failure("empty", 0, 0), False)
    equal("parse-failure: one stray link (a nav flyout) is not one",
          page_flow.looks_like_a_parse_failure("empty", 0, 1), False)
    # Nor is a page that parsed fine, nor a block.
    equal("parse-failure: a page with rows is never one",
          page_flow.looks_like_a_parse_failure("content", 24, 24), False)
    equal("parse-failure: a BLOCKED page is not one either",
          page_flow.looks_like_a_parse_failure("blocked", 0, 5), False)


def check_parser_found_nothing_is_not_a_complete_run():
    """The stop_reason must not read as success (blocked != empty)."""
    from output_writer import COMPLETE_STOP_REASONS, run_meta
    check("parse-failure: 'parser_found_nothing' is NOT a complete stop reason",
          "parser_found_nothing" not in COMPLETE_STOP_REASONS,
          list(COMPLETE_STOP_REASONS))
    meta = run_meta(status="failed", stop_reason="parser_found_nothing",
                    pages_requested=1, pages_completed=0, pages_failed=[1],
                    products=0, mode="listing", source="maison.kose.co.jp",
                    start_url="u", final_url="u")
    equal("parse-failure: the sidecar carries the reason by name",
          meta["stop_reason"], "parser_found_nothing")

    # Every engine must be able to SET it, or the sidecar can never say it.
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        check("%s can report parser_found_nothing" % module,
              "parser_found_nothing" in source,
              "the engine never sets the stop_reason, so it is unreachable")
        check("%s consults page_flow for it" % module,
              "looks_like_a_parse_failure" in source,
              "the engine must not reimplement the decision")


def check_sidecar_shape():
    from output_writer import run_meta
    # /c/c15/ states 13 pages and 12 x 24 + 16 = 304 products is all of
    # Cosme Decorte (measured 2026-09-18, see output_writer).
    meta = run_meta(status="complete", stop_reason="page_cap_reached",
                    pages_requested=50, pages_completed=13, pages_failed=[],
                    products=304, mode="listing", source="maison.kose.co.jp",
                    start_url="https://maison.kose.co.jp/site/cosmedecorte/c/c15/",
                    final_url="https://maison.kose.co.jp/site/cosmedecorte/c/c15_p13/",
                    extra={"pages_available": 13, "page_size": 24,
                           "canonical_url": "https://maison.kose.co.jp/site/cosmedecorte/c/c15/",
                           "route": "category"})
    for key in ("status", "stop_reason", "pages_requested", "pages_completed",
                "pages_failed", "mode", "source"):
        check("the sidecar records %r" % key, key in meta)
    equal("the sidecar carries the site's own page count",
          meta["pages_available"], 13)
    equal("...and the page size it applied", meta["page_size"], 24)
    equal("...and the page the SITE says was read", meta["canonical_url"],
          "https://maison.kose.co.jp/site/cosmedecorte/c/c15/")
    equal("...and which listing route it was", meta["route"], "category")
    # No `locale` and no `sort_requested`: one market, no ordering control.
    check("no locale on a one-market site", "locale" not in meta, sorted(meta))
    equal("pages_failed is a LIST of numbers, not a count",
          isinstance(meta["pages_failed"], list), True)

    # No `capped_by_site` here, and the ABSENCE is the finding: this site
    # imposes no page cap, so a complete run really is the whole category.
    check("no capped_by_site on a site that does not cap",
          "capped_by_site" not in meta, sorted(meta))


def check_row_schema():
    from output_writer import Product, ROW_CLASS_BY_MODE, UNIQUE_BY_SKU_MODES
    names = [f.name for f in fields(Product)]
    equal("the family prefix is byte-identical and in order",
          names[:5], ["source", "scraped_at", "url", "sku", "title"])

    # The commerce columns this site DOES have. Maison KOSÉ is a shop, so the
    # family's price fields are present rather than dropped.
    for present in ("brand", "price", "currency", "in_stock", "image_url",
                    "category", "price_source"):
        check("the commerce column %r is present" % present, present in names)

    # And the ones measured ABSENT, each with its count in output_writer's
    # docstring. Removing a column needs the measurement written
    # down; this pins that they stay removed until someone re-measures.
    for gone in ("original_price", "discount_pct", "lowest_price_30d",
                 "rating", "review_count", "ean", "gtin", "engraved"):
        check("the column %r is absent, not null-forever" % gone,
              gone not in names,
              "if this is back, output_writer's measurement should be too")

    # Site-specific columns go at the END of the row, after the family's.
    equal("site-specific columns come last",
          names[-9:], ["mode", "tax_rate", "price_is_store_price", "badges",
                       "subcategory", "volume", "colour_count",
                       "release_date", "variant_of"])

    equal("every mode maps to a row class",
          sorted(ROW_CLASS_BY_MODE), ["listing", "product"])
    equal("every mode is one row per sku",
          sorted(UNIQUE_BY_SKU_MODES), ["listing", "product"])
    equal("both modes share one class",
          len({c for c in ROW_CLASS_BY_MODE.values()}), 1)


def check_fixtures_carry_no_session_material():
    """A real page dump carries the session that fetched it.

    A sibling repo committed three `sessionId` values, their CSRF tokens and
    a real customer's display name, profile permalink and review text. None
    of that granted anything — the session material was anonymous and
    expired — and it still did not belong in a public repo.

    Maison KOSÉ is the easy case: it publishes products, not people, and no
    capture here carries a name, a review or a login. So this guards the
    SHAPE rather than any literal, which is the half that keeps working when
    the next capture is taken (guard with PATTERNS, not the old
    values).
    """
    fixtures = {
        "LISTING_HTML": LISTING_HTML,
        "LISTING_TAX8_HTML": LISTING_TAX8_HTML,
        "TAGS_HTML": TAGS_HTML,
        "PRODUCT_HTML": PRODUCT_HTML,
        "EMPTY_HTML": EMPTY_HTML,
        "NOTFOUND_HTML": NOTFOUND_HTML,
        "CHROMIUM_ERROR_HTML": CHROMIUM_ERROR_HTML,
    }
    patterns = {
        "a session id": r"sessionId|session_id|JSESSIONID|dwsid",
        "a CSRF token": r"csrf[_-]?token|anti-?csrftoken",
        "a bearer token": r"[Bb]earer\s+[A-Za-z0-9._-]{16,}",
        "a 32-hex key": r"\b[0-9a-f]{32}\b",
        "an email address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
        "credentials in a URL": r"[a-z]+://[^\s/@]+:[^\s/@]+@",
    }
    for fixture_name, text in fixtures.items():
        for label, pattern in patterns.items():
            hit = re.search(pattern, text)
            check("%s carries no %s" % (fixture_name, label), hit is None,
                  "matched %r — scrub the capture before committing it"
                  % (hit.group(0)[:40] if hit else ""))


def _import_engine(name):
    try:
        return __import__(name)
    except ImportError as e:
        skip(name, "engine library absent (%s)" % e)
        return None


def _argparse_flags(module_name):
    """Every --flag a module's parser defines, without running the CLI."""
    path = os.path.join(HERE, module_name + ".py")
    tree = ast.parse(open(path, encoding="utf-8").read())
    # Only calls on the argparse parser itself. A browser's option object
    # also has `add_argument`, and counting Chrome's own switches
    # (`--no-sandbox`, `--window-size=…`) as CLI flags made this check
    # compare nonsense.
    parsers = {"p"}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr in ("add_argument_group",
                                             "add_mutually_exclusive_group")):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    parsers.add(target.id)
    flags = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in parsers):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) \
                        and arg.value.startswith("--"):
                    flags.add(arg.value)
    return flags


def _tree_state():
    result = subprocess.run(["git", "status", "--porcelain"], cwd=HERE,
                            capture_output=True, text=True)
    if result.returncode != 0:
        return None
    return sorted(line for line in result.stdout.splitlines()
                  if not line.endswith(".pyc"))


def _import_graph(entrypoint):
    """Every local module an entrypoint reaches, transitively."""
    local = {f[:-3] for f in os.listdir(HERE) if f.endswith(".py")}
    seen, queue = set(), [entrypoint]
    while queue:
        name = queue.pop()
        if name in seen or name not in local:
            continue
        seen.add(name)
        tree = ast.parse(open(os.path.join(HERE, name + ".py"),
                              encoding="utf-8").read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                queue.extend(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                queue.append(node.module.split(".")[0])
    return seen

def check_the_credential_scan_skips_a_virtualenv_whatever_it_is_called():
    """A venv is detected structurally, not by directory name.

    Found by cloning this repo fresh and following its own README with the
    environment called `.v`: pip's vendored `packaging/_elffile.py` carries a
    32-hex string, so the credential scan failed on a perfectly clean clone.
    A name-based skip list covers the names its author happened to think of
    and fails for everyone else — the "a check that fails on its
    own repository is a check nobody can read", one step out.

    The control matters as much as the check: the fixture below is
    built so that WITHOUT the fix it really would fail, which is asserted
    rather than assumed.
    """
    sys.path.insert(0, os.path.join(HERE, ".github"))
    try:
        import ci_checks
    except ImportError as e:
        skip("ci_checks", str(e))
        return

    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "repo")
        os.makedirs(os.path.join(root, "weirdname", "lib", "python3.13",
                                 "site-packages", "pip"))
        # A venv is what it is because of this file, not because of its name.
        open(os.path.join(root, "weirdname", "pyvenv.cfg"), "w").write(
            "home = /usr/bin\nversion = 3.13.5\n")
        planted = os.path.join(root, "weirdname", "lib", "python3.13",
                               "site-packages", "pip", "vendored.py")
        # The shape the scan is looking for, in a file that is not ours.
        open(planted, "w").write("MAGIC = '%s'\n" % ("a1b2c3d4" * 4))
        open(os.path.join(root, "mine.py"), "w").write("x = 1\n")

        before = ci_checks.REPO
        try:
            ci_checks.REPO = __import__("pathlib").Path(root)
            found = sorted(str(p.relative_to(root)) for p in ci_checks.scanned_files())
            equal("only the repo's own file is scanned", found, ["mine.py"])
            # The control: the planted file really is there and really does
            # carry the shape, so a scan that did NOT skip it would fail.
            check("the control is real — the planted file exists",
                  os.path.exists(planted))
            check("...and really carries a 32-hex string",
                  bool(ci_checks.HEX32.findall(open(planted).read())))
            equal("the credential scan is therefore clean",
                  ci_checks.secret_check(), [])
        finally:
            ci_checks.REPO = before


def check_the_credential_scan_reads_a_clone_under_any_parent():
    """The skip list is applied to the path RELATIVE to the repository.

    It used to test the absolute path, so a clone that merely lived under a
    directory named `build` or `dist` — both in the skip list — scanned no
    files at all and printed "0 files scanned, nothing credential-shaped".
    A scan that reads nothing must fail, not pass; and a renamed `.env`
    backup, which is where a live key actually sits, must be read.
    """
    sys.path.insert(0, os.path.join(HERE, ".github"))
    try:
        import ci_checks
    except ImportError as e:
        skip("ci_checks", str(e))
        return
    import pathlib
    key = "f0e1d2c3" * 4     # assembled, so this file does not carry the shape
    before = ci_checks.REPO
    try:
        for parent in ("build", "dist", "plain"):
            with tempfile.TemporaryDirectory() as tmp:
                root = os.path.join(tmp, parent, "kose-scraper")
                os.makedirs(root)
                open(os.path.join(root, "planted.py"), "w").write(
                    "K = '%s'\n" % key)
                ci_checks.REPO = pathlib.Path(root)
                found = ci_checks.secret_check()
                check("a key planted in a clone under %s/ is caught" % parent,
                      any("planted.py" in f for f in found), str(found))
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "kose-scraper")
            os.makedirs(root)
            open(os.path.join(root, ".env.bak"), "w").write(
                "TWOCAPTCHA_KEY=%s\n" % key)
            ci_checks.REPO = pathlib.Path(root)
            found = ci_checks.secret_check()
            check("a key in an untracked .env.bak is caught",
                  any(".env.bak" in f for f in found), str(found))
        with tempfile.TemporaryDirectory() as tmp:
            ci_checks.REPO = pathlib.Path(tmp)
            check("a scan that read no files fails instead of passing",
                  bool(ci_checks.secret_check()))
    finally:
        ci_checks.REPO = before


def check_a_404_is_terminal_and_not_a_retry():
    """A discarded HTTP status turns a 404 into a retryable nothing.

    This site answers a missing PATH with a bare 1,040-byte page carrying no
    site chrome at all — 0 references to `/js/sys/` or `/freepage/` — so
    without a status it classifies as "unknown", which RETRIES and spends the
    budget on an address that will never exist. Measured 2026-09-18 on
    `/definitely-not-a-page`.

    Note what a 404 is NOT on this site: a bogus goods code or category id
    answers HTTP 200 with the full chrome and no tiles, which is `empty` — a
    correct answer about the CATALOGUE, where a 404 is an answer about the
    ADDRESS.
    """
    equal("the real 404 carries no site chrome",
          product_parser.references_own_assets(HTTP404_HTML), 0)
    equal("with the status threaded, it is not_found",
          page_flow.classify(HTTP404_HTML, 404), "not_found")
    equal("and it is terminal", page_flow.should_retry("not_found"), False)
    equal("and not a block — exit 3 would send the reader after a proxy",
          page_flow.counts_as_blocked("not_found"), False)
    equal("and there is nothing on it to parse",
          page_flow.should_parse("not_found"), False)
    equal("a served-but-empty page is still EMPTY, not not_found",
          page_flow.classify(EMPTY_HTML, 200), "empty")

    # Check the signal CAN fire before adding it. It can, on a URL this
    # scraper ACCEPTS: the tag route with no `tags=` parameter is a supported
    # address and answers HTTP 404 (measured 2026-09-18). A user who pastes
    # the bare facet URL lands exactly here, so the branch is reachable
    # rather than decorative.
    bare_tags = "https://maison.kose.co.jp/site/itemtags/list.aspx"
    ok, why = product_parser.is_supported_url(bare_tags)
    check("the bare tag URL is accepted, so a 404 can reach the classifier",
          ok, why)
    equal("...and so is a bogus goods code, which answers 200",
          page_flow.classify(NOTFOUND_HTML, 200), "empty")


def check_all_three_engines_agree_about_a_404():
    """Selenium cannot read an HTTP status; it must still agree.

    `driver.get()` returns None and WebDriver exposes no status at all, so
    the parser reads the one the site states in its own error page. Without
    that, two engines would be better informed than the third and would
    report different exit codes for the same response — the drift a shared
    module exists to prevent.
    """
    equal("the site states its status in its own title",
          product_parser.status_from_body(HTTP404_HTML), 404)
    equal("Playwright / pyppeteer, which thread the real status",
          page_flow.classify(HTTP404_HTML, 404), "not_found")
    equal("Selenium, which cannot, via the body reader",
          page_flow.classify(HTTP404_HTML, None), "not_found")
    # And the reader must not invent a status out of ordinary pages.
    for name, html in (("listing", LISTING_HTML), ("product", PRODUCT_HTML),
                       ("tags", TAGS_HTML), ("empty", EMPTY_HTML),
                       ("served-empty goods code", NOTFOUND_HTML)):
        equal("no status read out of the %s fixture" % name,
              product_parser.status_from_body(html), None)


def check_the_engines_really_thread_a_status():
    """Asserted in the SOURCE, because a live 404 is what it takes otherwise.

    The memory this fixes was written after all three engines in a sibling
    repo discarded `goto()`'s response: `--help`, `compileall`, an
    undefined-name walk and 570 offline checks all passed on it, and only a
    real run reached a 404. So this reads the engines rather than running
    them, and asserts the shape that cannot be checked any other way.
    """
    for module in ("playwright_scraper", "puppeteer_scraper"):
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        source = open(path, encoding="utf-8").read()
        check("%s binds the navigation response" % module,
              "response = " in source and "response.status" in source,
              "goto() returns a response and this engine can read it")
        # Every classify CALL SITE, bound by an ast walk rather than by
        # grepping for the variable name anywhere in the file. The first
        # version of this check did the latter and passed for the wrong
        # reason: reverting the fix left `http_status` declared and unused,
        # and the check went on saying green (verify that your control
        # actually failed).
        tree = ast.parse(source)
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else getattr(fn, "id", None))
            if name not in ("classify", "classify_with_reason", "_classify"):
                continue
            calls.append(node)
        check("%s has classify call sites to check" % module, bool(calls))
        for node in calls:
            args = list(node.args) + [k.value for k in node.keywords
                                      if k.arg == "status"]
            threaded = any(isinstance(a, ast.Name) and "status" in a.id
                           for a in args)
            check("%s:%d passes a status to the classifier"
                  % (module, node.lineno), threaded,
                  "this engine CAN read one from goto(), so a None here "
                  "turns a 404 into a retryable nothing")
    sel = os.path.join(HERE, "selenium_scraper.py")
    if os.path.exists(sel):
        # Comment markers stripped and whitespace normalised, because the
        # sentence wraps across lines in the source. A literal match would
        # be testing the line width rather than what the file says.
        raw = open(sel, encoding="utf-8").read()
        source = re.sub(r"\s+", " ", re.sub(r"(?m)^\s*#", " ", raw))
        check("selenium_scraper says WHY it threads no status",
              "WebDriver exposes no HTTP status" in source,
              "an engine that cannot do what its twins do must say so, or "
              "the next reader 'fixes' it by copying their code")


def check_x_debug_header_is_redacted():
    """SECURITY.md names the Scraper API's x-debug header as a place
    credentials reach a log unmasked. It was then logged verbatim.

    The fixtures are assembled from pieces rather than written out whole,
    because this file is scanned by the credential check like every other
    and a fixture that LOOKS like a live key fails it. They are the SHAPES a
    credential takes, not the literals this repo happens to contain today.
    """
    try:
        import scraper_api_client as sac
    except ImportError:
        return

    pw = "SeCr" + "EtPw"
    key = "abcdef01" * 4
    raw = ("cdpurl=ws://acct-zone-scraping_browser-pid-7:" + pw
           + "@cb.2captcha.com:9222 cost=0.00145 key=" + key + " status=200")
    out = sac._redact_debug_header(raw)
    check("x-debug: the credential and the key are gone",
                 pw not in out and key not in out)
    check("x-debug: the cost, host and status survive",
                 "cost=0.00145" in out and "cb.2captcha.com:9222" in out
                 and "status=200" in out)

    s1, s2 = "secret" + "one", "secret" + "two"
    two = sac._redact_debug_header(
        "a=http://u1:" + s1 + "@h1:1 b=http://u2:" + s2 + "@h2:2")
    check("x-debug: both credentials are masked, not just the first",
                 s1 not in two and s2 not in two)

    src = inspect.getsource(sac)
    check("x-debug: the log line calls the redactor",
                 'logger.info("x-debug: %s", _redact_debug_header(debug))' in src)


def check_scraper_api_waitfor_object_and_http_code():
    """Measured 2026-09-23 against the live Scraper API: `waitFor` sent as
    a JSON-encoded string is refused with HTTP 422 and still billed, and
    the response's `status` is the API's verdict ("success") while the
    target's own code is `http_code`. Drives the real fetch_html with
    requests.post replaced, so no network and no money."""
    import argparse
    import logging
    import scraper_api_client as sac
    captured = {}

    class _Resp:
        status_code = 200
        headers = {}
        text = ""

        def json(self):
            return {"status": "success", "http_code": 403, "body": "<html></html>"}

    def _fake_post(url, **kw):
        captured["json"] = kw.get("json")
        return _Resp()

    logged = []

    class _H(logging.Handler):
        def emit(self, record):
            if str(record.msg).startswith("Upstream page status"):
                logged.append(record.args[0])

    h = _H()
    real_post = sac.requests.post
    sac.requests.post = _fake_post
    sac.logger.addHandler(h)
    result = None
    try:
        args = argparse.Namespace(url='https://maison.kose.co.jp/site/cosmedecorte/c/c15/', key="k", timeout=60, cdp_url=None,
                                  wait_text='円', wait_element=None,
                                  wait_state=None)
        result = sac.fetch_html(args)
    finally:
        sac.requests.post = real_post
        sac.logger.removeHandler(h)
    # Where fetch_html returns (html, status) the status handed onward is
    # the second element; where it returns only the html, the log line is
    # the only place the status goes.
    handed = result[1] if isinstance(result, tuple) else (logged[0] if logged else None)
    wf = (captured.get("json") or {}).get("waitFor")
    check("Scraper API: --wait-text sends waitFor as an OBJECT, not a JSON string "
                "(a string is HTTP 422 and still billed, measured 2026-09-23)",
                isinstance(wf, dict) and wf.get("text") == '円')
    check("Scraper API: the target status handed onward is http_code (403, an int), "
                "not the API's own 'success' verdict",
                type(handed) is int and handed == 403 and logged == [403])



class _StubDriver:
    """Enough of a driver for the shared fetch loop, in all three dialects.

    One object answering every engine's primitives on purpose. The first
    version of this stub spoke only Playwright's (`goto`, `content`), so the
    Selenium control failed with `'_StubPage' object has no attribute 'get'`
    — red both with the fix and without it, which is a broken check wearing
    a working control's clothes (check WHICH check caught the fault).
    """
    url = LISTING_URL
    current_url = LISTING_URL
    page_source = "<html><body>x</body></html>"

    # Playwright
    def goto(self, *a, **k):
        return _StubResponse()

    def content(self):
        return self.page_source

    def wait_for_timeout(self, ms):
        pass

    def query_selector_all(self, selector):
        return []

    def set_default_timeout(self, ms):
        pass

    def set_default_navigation_timeout(self, ms):
        pass

    # Selenium
    def get(self, url):
        return None

    def find_elements(self, by, selector):
        return []

    def execute_script(self, *a, **k):
        return None

    def execute_cdp_cmd(self, *a, **k):
        return {}

    # pyppeteer (awaited through the session's bridge, which here is sync)
    def querySelectorAll(self, selector):
        return []

    def evaluate(self, *a, **k):
        return None

    def setDefaultNavigationTimeout(self, ms):
        pass

    # After a solve: Playwright and pyppeteer reload, Selenium refreshes.
    def reload(self, *a, **k):
        return _StubResponse()

    def refresh(self):
        return None


class _StubResponse:
    status = 200


class _StubSession:
    """`relaunch` must never be reached without a pool, which is half of
    what the check above asserts."""

    def __init__(self):
        self.page = _StubDriver()
        self.driver = self.page
        self.bridge = self
        self.relaunched = 0

    def relaunch(self):
        self.relaunched += 1

    def run(self, value):
        return value


def _stub_args():
    import types
    return types.SimpleNamespace(
        pages=1, retries=1, retry_delay=0.0, mode="listing",
        out=os.path.join(tempfile.gettempdir(), "kose_stub"),
        proxy_block_retries=2, dump_html=None, category=None,
        solve_captcha="when-blocked", twocaptcha_key=None, min_score=0.7,
        captcha_api="v2", concurrency=1, allow_empty=False)



# ---------------------------------------------------------------------------
# From the 2026-10-13 audit round. Each of these pins a defect that was real
# in this repo, and each was controlled: the fix reverted, the named check
# confirmed red, the fix restored.
# ---------------------------------------------------------------------------

def check_retries_zero_is_a_usage_error():
    """`--retries 0` ran NO navigation and then judged the blank page.

    The load loop is `range(1, retries + 1)`; with 0 it never executes, so
    `goto` is not called and the engine classifies `about:blank` — 39 bytes
    of empty document — as a result for a site that was never asked.

    This is not hypothetical and it is not cosmetic. A third-party audit of
    this repo on 2026-10-13 ran exactly that, got the 39-byte page and exit
    4, and concluded in writing that the browser path was broken and should
    be replaced by an HTTP one. The same command with `--retries 1`, same
    address and same minute, returned 199,558 bytes and 24 products.
    """
    equal("--retries 3 is accepted", page_flow.attempts("3"), 3)
    equal("--retries 1 is accepted", page_flow.attempts("1"), 1)
    for bad in ("0", "-1", "x"):
        raised = False
        try:
            page_flow.attempts(bad)
        except argparse.ArgumentTypeError:
            raised = True
        check("--retries %s is refused as a usage error" % bad, raised)
    # The billable path counts RETRIES rather than attempts, where 0 is
    # meaningful: it means one attempt. Only a negative is refused there.
    equal("the Scraper API path accepts 0", page_flow.extra_attempts("0"), 0)
    raised = False
    try:
        page_flow.extra_attempts("-1")
    except argparse.ArgumentTypeError:
        raised = True
    check("...and refuses a negative", raised)

    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        check("%s: --retries goes through page_flow.attempts" % module,
              '"--retries", type=page_flow.attempts' in src,
              "a plain type=int lets 0 through and the loop then runs never")


def check_counts_and_pauses_refuse_negative_values():
    """--pages/--concurrency must be >= 1; pauses and block retries >= 0.

    A plain `type=int` let `--pages 0` through to a run that fetched nothing
    and reported an empty catalogue, and a negative `--delay` reached
    `time.sleep` after page 1 had been fetched and crashed the run there.
    """
    for good, fn, want in (("2", page_flow.at_least_one, 2),
                           ("0", page_flow.non_negative_int, 0),
                           ("0", page_flow.non_negative_seconds, 0.0),
                           ("1.5", page_flow.non_negative_seconds, 1.5)):
        equal("%s(%r) is accepted" % (fn.__name__, good), fn(good), want)
    for bad, fn in (("0", page_flow.at_least_one), ("-1", page_flow.at_least_one),
                    ("-1", page_flow.non_negative_int),
                    ("-0.5", page_flow.non_negative_seconds),
                    ("nan", page_flow.non_negative_seconds)):
        raised = False
        try:
            fn(bad)
        except argparse.ArgumentTypeError:
            raised = True
        check("%s(%r) is refused as a usage error" % (fn.__name__, bad), raised)

    wanted = {
        "--pages": "page_flow.at_least_one",
        "--concurrency": "page_flow.at_least_one",
        "--delay": "page_flow.non_negative_seconds",
        "--retry-delay": "page_flow.non_negative_seconds",
        "--proxy-block-retries": "page_flow.non_negative_int",
    }
    for module in ENGINES + ("http_scraper",):
        src = open(os.path.join(HERE, module + ".py"), encoding="utf-8").read()
        for flag, typ in wanted.items():
            if '"%s"' % flag not in src:
                continue
            check("%s: %s goes through %s" % (module, flag, typ),
                  '"%s", type=%s' % (flag, typ) in src,
                  "a plain type=int/float lets a negative through")
    src = open(os.path.join(HERE, "scraper_api_client.py"), encoding="utf-8").read()
    check("scraper_api_client: --retry-delay refuses a negative",
          '"--retry-delay", type=page_flow.non_negative_int' in src)


def check_a_blocked_page_without_a_proxy_does_not_crash():
    """Selenium and pyppeteer raised AttributeError on a blocked page.

    `mask(pool.current)` with no `--proxy` is `None.current`. Without a pool
    `BLOCK_RETRIES_WITHOUT_POOL` is 1, so the branch runs on the FIRST block
    — and the run exited 1, a CRASH, for a page that was merely blocked.
    That destroys the blocked/empty/partial distinction the exit codes
    exist for, and the primary engine had the guard all along: it is the
    "all three must agree" rule broken in the two quiet engines.

    Asserted as BEHAVIOUR rather than by reading the source: the first
    version of this check walked the AST for an unguarded `pool.` attribute
    and reported every engine broken, including the one that was correct.
    This drives the real loop with no pool and a forced block, and asks only
    that it does not raise.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue

        calls = []
        saved = (engine.handle_captcha_if_present,
                 page_flow.classify, page_flow.classify_with_reason,
                 getattr(engine, "_snapshot", None))
        try:
            engine.handle_captcha_if_present = lambda *a, **k: calls.append(1)
            page_flow.classify = lambda html, status=None, url="": "blocked"
            page_flow.classify_with_reason = (
                lambda html, status=None, url="": ("blocked", "stub"))
            engine._snapshot = lambda *a, **k: "<html><body>x</body></html>"

            session = _StubSession()
            args = _stub_args()
            raised = None
            try:
                outcome = engine._fetch_one_page(
                    session, args, None, 1, LISTING_URL)   # pool=None
            except Exception as e:                          # noqa: BLE001
                raised, outcome = e, None
            check("%s: a blocked page with no --proxy does not raise" % module,
                  raised is None, "%s: %s" % (type(raised).__name__, raised)
                  if raised else "")
            if outcome is not None:
                check("%s: ...and is reported as blocked, not as a crash"
                      % module, outcome.blocked_by is not None,
                      str(outcome.state))
        finally:
            (engine.handle_captcha_if_present, page_flow.classify,
             page_flow.classify_with_reason, snap) = saved
            if snap is not None:
                engine._snapshot = snap



# The exception each engine's load loop treats as a navigation timeout.
_LOAD_TIMEOUT_TYPE = {
    "playwright_scraper": "PWTimeout",
    "selenium_scraper": "TimeoutException",
    "puppeteer_scraper": None,      # catches Exception: pyppeteer raises many
}


def check_a_page_that_never_loads_without_a_proxy_does_not_crash():
    """pyppeteer raised AttributeError when a page failed to load, no pool.

    The blocked branch had been fixed, but the LOAD-FAILURE branch still
    called `pool.advance(...)` with no `--proxy`, where `pool` is None:
    a page whose navigation timed out `--retries` times ended the run with a
    traceback and exit 1 instead of a load failure (exit 5, or 6 with rows).
    The other two engines rotate only for an unusable exit and only when a
    pool has another exit in it.

    Driven as behaviour, with a navigation that always times out and,
    separately, one that fails with Chromium's dead-proxy error text.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        type_name = _LOAD_TIMEOUT_TYPE[module]
        exc_type = getattr(engine, type_name) if type_name else Exception
        for label, text in (("a timeout", "Navigation timeout of 60000 ms"),
                            ("a dead proxy", "net::ERR_PROXY_CONNECTION_FAILED")):
            session = _StubSession()
            gotos = []

            def fail(*a, **k):
                gotos.append(1)
                raise exc_type(text)
            session.page.goto = fail
            session.page.get = fail
            args = _stub_args()
            args.retries = 2
            raised, outcome = None, None
            try:
                outcome = engine._fetch_one_page(
                    session, args, None, 1, LISTING_URL)   # pool=None
            except Exception as e:                          # noqa: BLE001
                raised = e
            check("%s: %s with no --proxy does not raise" % (module, label),
                  raised is None, "%s: %s" % (type(raised).__name__, raised)
                  if raised else "")
            check("%s: %s was actually attempted" % (module, label),
                  bool(gotos), "goto was never called")
            if outcome is not None:
                check("%s: ...and is reported as a load failure" % (module,)
                      + " (%s)" % label, outcome.load_failed)
            check("%s: ...and no relaunch without a pool (%s)" % (module, label),
                  session.relaunched == 0, str(session.relaunched))


class _StubChallenge:
    kind, source, sitekey, action = "recaptcha-v2", "stub", "stub-key", None


def _drive_budget(engine, detections, solver_raises=False):
    """Run one page with a forced challenge and no pool; return purchases.

    `detections` is the sequence of answers the detector gives, one per
    call to `handle_captcha_if_present`: None for "nothing here", True for
    "a challenge". Nothing reaches the network: the solver is a stub.
    """
    answers = list(detections)
    purchases = []

    def reconcile(*a, **k):
        hit = answers.pop(0) if answers else True
        return _StubChallenge() if hit else None

    def solve(*a, **k):
        purchases.append(1)
        if solver_raises:
            raise RuntimeError("stub solver failure")
        return "stub-token"

    names = ("detect_recaptcha_v3", "detect_recaptcha_in_page",
             "reconcile_detections", "solve_recaptcha")
    saved = {n: getattr(engine, n) for n in names}
    saved_pf = (page_flow.classify, page_flow.classify_with_reason)
    try:
        engine.detect_recaptcha_v3 = lambda *a, **k: None
        engine.detect_recaptcha_in_page = lambda *a, **k: None
        engine.reconcile_detections = reconcile
        engine.solve_recaptcha = solve
        page_flow.classify = lambda html, status=None, url="": "challenge"
        page_flow.classify_with_reason = (
            lambda html, status=None, url="": ("challenge", "stub"))
        args = _stub_args()
        args.twocaptcha_key = "stub-not-a-key"
        engine._fetch_one_page(_StubSession(), args, None, 1, LISTING_URL)
    finally:
        for n, v in saved.items():
            setattr(engine, n, v)
        page_flow.classify, page_flow.classify_with_reason = saved_pf
    return len(purchases)


def check_the_solve_allowance_is_spent_only_on_a_purchase():
    """A detection that buys nothing must not use up the page's allowance.

    The allowance used to be counted per CALL to the detector. The
    pre-classification call runs on every attempt and, on a normal page,
    detects nothing — yet it consumed the one solve a page is allowed, so a
    challenge first seen after classification was never offered to the
    solver and the page came out blocked.

    Both directions are pinned, because this is the paid path: a late
    challenge gets exactly one purchase, a challenge seen on every call
    still gets exactly one, and a purchase that FAILS still counts.
    """
    for module in ENGINES:
        engine = _import_engine(module)
        if engine is None:
            continue
        limit = page_flow.SOLVES_PER_PAGE
        equal("%s: a challenge seen only after classification is solved"
              % module, _drive_budget(engine, [None]), limit)
        equal("%s: a challenge seen on every call is bought once per page"
              % module, _drive_budget(engine, []), limit)
        equal("%s: a failed purchase still counts against the allowance"
              % module, _drive_budget(engine, [], solver_raises=True), limit)


def check_every_paid_solve_goes_through_one_budget():
    """`handle_captcha_if_present` runs TWICE per attempt; one was uncounted.

    Measured on this repo with the solver stubbed and a forced challenge:
    **3 invocations against `SOLVES_PER_PAGE = 1`** before the fix, 1 after.
    The uncounted call repeats on every block-retry, so the constant read
    like a limit and was advisory.

    Asserted by PARSING rather than by grepping, because a grep for
    `SOLVES_PER_PAGE` matches the constant, the comment that explains it and
    the docstring of the function it guards — in a repo where the guard does
    not cover the call.
    """
    for module in ENGINES:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        guarded, calls = set(), []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and any(
                    k in ast.dump(node.test)
                    for k in ("budget", "solves_bought", "SOLVES_PER_PAGE")):
                for part in [node.test] + node.body:
                    for sub in ast.walk(part):
                        if isinstance(sub, ast.Call):
                            guarded.add(id(sub))
            if isinstance(node, ast.Call):
                name = (getattr(node.func, "id", None)
                        or getattr(node.func, "attr", None))
                if name and "captcha" in name.lower() and "present" in name.lower():
                    calls.append(node)
        check("%s has captcha call sites to check" % module, bool(calls))
        unbudgeted = [c.lineno for c in calls if id(c) not in guarded]
        check("%s: every paid solve is budgeted" % module, not unbudgeted,
              "unbudgeted at line(s) %s" % unbudgeted)


def check_output_is_written_atomically():
    """`open(path, "w")` truncates before a byte is written.

    A crash, a kill or a full disk halfway through leaves a SHORTER file
    where a complete one was — which breaks exactly the promise `save()`
    keeps by refusing to overwrite good output with an empty result. The
    sidecar is the part that matters most: a truncated `<out>.meta.json`
    beside good rows reads as a broken run over data that is fine.
    """
    import inspect
    writers = []
    for name in dir(output_writer):
        fn = getattr(output_writer, name)
        if not callable(fn) or getattr(fn, "__module__", None) != "output_writer":
            continue
        try:
            src = inspect.getsource(fn)
        except (OSError, TypeError):
            continue
        if "open(" not in src and "_atomic(" not in src:
            continue
        if not any(k in src for k in ("json.dump", "csv.DictWriter", ".meta.json")):
            continue
        writers.append((name, "_atomic(" in src))
    check("the probe found the writers at all", len(writers) >= 3,
          str(writers))
    for name, atomic in writers:
        check("output_writer.%s writes atomically" % name, atomic)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "out.json")
        rows = [Product(sku="A", title="x")]
        output_writer.write_json(rows, path)
        before = open(path, "rb").read()

        class _Boom(Exception):
            pass
        try:
            with output_writer._atomic(path) as f:
                f.write("half a file")
                raise _Boom()
        except _Boom:
            pass
        equal("an interrupted write leaves the good file untouched",
              open(path, "rb").read(), before)
        check("and leaves no .tmp behind",
              not [x for x in os.listdir(tmp) if x.endswith(".tmp")])

        # NamedTemporaryFile creates at 0600 and os.replace keeps the temp
        # file's mode, so without the chmod every output comes out readable
        # by its owner alone — a regression from open(), which honours the
        # umask, and one that appears only once the write became atomic.
        umask = os.umask(0)
        os.umask(umask)
        equal("a NEW file gets what open() would have given it",
              stat.S_IMODE(os.stat(path).st_mode), 0o666 & ~umask)
        os.chmod(path, 0o600)
        output_writer.write_json(rows, path)
        equal("an EXISTING file keeps its own mode, however tightened",
              stat.S_IMODE(os.stat(path).st_mode), 0o600)


def check_csv_formula_cells_are_neutralised():
    """A cell beginning `=`, `+`, `-`, `@` or whitespace is a FORMULA.

    Every string in these rows was written by whoever listed the product.
    CSV only: the JSON keeps the site's bytes, and `csv_cells_escaped` in
    the sidecar declares the divergence rather than leaving it to be found
    as a stray apostrophe.

    It does NOT fire on this site — 0 of 42,  measured over a live run — and
    that is worth shipping and not worth advertising as a catch.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "t.csv")
        rows = [Product(sku="A", title='=HYPERLINK("http://x","go")', price=1.0),
                Product(sku="B", title="+cmd|' /c calc'!A1"),
                Product(sku="C", title="ふつうの商品名", price=-5.0)]
        escaped = output_writer.write_csv(rows, path)
        equal("two formula-shaped cells were neutralised", escaped, 2)
        got = list(csv.DictReader(open(path, encoding="utf-8")))
        check("the formula cell is prefixed",
              got[0]["title"].startswith(output_writer.CSV_FORMULA_ESCAPE))
        equal("an ordinary title is untouched", got[2]["title"], "ふつうの商品名")
        # Escaping a number would turn -5 into text and break every sum a
        # consumer writes over the column.
        equal("a NEGATIVE NUMBER is left alone", got[2]["price"], "-5.0")


def check_the_sites_own_truncation_is_undone():
    """The site shortens a long name in the BROWSER, and only there.

    Each tile carries `data-module="TruncateText" data-options='{"length":
    36}'`, and the site's own JavaScript rewrites the name node after load:
    36 characters and an ellipsis. A plain HTTP fetch sees the full name the
    server rendered; a browser sees the short one.

    So for as long as this repo had only browser engines, it returned a
    SHORTER title than the site publishes for every long name, and nothing
    could see it — there was no non-browser engine to disagree with. It took
    `http_scraper.py` existing: on one live 3-page run the two engines
    differed on **10 of 72 rows**, every one of them a title.

    The rule is narrow on purpose. `0 of 171` server-rendered names in the
    captures end in an ellipsis, while every truncated one does, so the
    marker is unambiguous — and the thumbnail's `alt`, which the rewrite
    does not touch, is present on 171 of 171 and differs from the
    server-rendered name on zero of them once whitespace is normalised.
    """
    full = "リポソーム アドバンスト リペアクリーム パープルリボン セット 2026"
    tile = ('<ul><li class="c-product__item">'
            '<div class="c-product__thumb">'
            '<a href="/site/x/g/gAAA/" class="c-product__thumb__img">'
            '<img src="/img/goods/S/AAA_sub.png" alt="%s" /></a></div>'
            '<div class="c-product__about">'
            '<p class="c-product__brand">コスメデコルテ</p>'
            '<a href="/site/x/g/gAAA/"><p class="c-product__product-name" '
            'data-module="TruncateText" data-options=\'{ "length": 36 }\'>'
            '%s…</p></a>'
            '<p class="c-product__price">1,000円<span>（税込）</span></p>'
            '</div><div class="btn-items-cart"><a>カートに入れる</a></div>'
            '</li></ul>') % (full, full[:36])
    rows = product_parser.parse_products(tile, LISTING_URL)
    equal("a truncated tile recovers the full name", rows[0].title, full)

    # And an ordinary tile is untouched: the fixtures carry no ellipsis, so
    # nothing here may change what they parse to.
    for row in product_parser.parse_products(LISTING_HTML, LISTING_URL):
        check("an untruncated title is left alone (%s)" % row.sku,
              not row.title.endswith(("…", "...")), row.title)

    # A site that one day ships an empty or SHORTER alt must not make a
    # title worse than the truncated text already is.
    worse = tile.replace('alt="%s"' % full, 'alt=""')
    equal("an empty alt leaves the truncated text in place",
          product_parser.parse_products(worse, LISTING_URL)[0].title,
          full[:36] + "…")


def check_the_http_engine_is_the_same_scrape():
    """A fourth engine, over `requests`, reading the same parser.

    It exists because this site server-renders its grid and gates nothing —
    measured 2026-10-13, a project UA, a requests UA, a Chrome UA and NO UA
    at all are served byte-identical pages — so a browser buys nothing here.
    Live on the same two pages, all four engines returned 48 of 48 identical
    rows.

    What it must NOT do is accept a flag it cannot honour: a setting that
    looks configurable and does nothing is worse than one that is absent
. Those are refused as usage errors.
    """
    path = os.path.join(HERE, "http_scraper.py")
    if not os.path.exists(path):
        check("http_scraper.py exists", False)
        return
    src = open(path, encoding="utf-8").read()

    check("it reads the shared parser, not its own",
          "from product_parser import" in src)
    check("it shares the output contract", "finish_run" in src)
    check("it shares the page-state policy", "page_flow.classify" in src)
    check("--retries goes through page_flow.attempts",
          '"--retries", type=page_flow.attempts' in src)
    check("it threads the HTTP status to the classifier",
          "page_flow.classify(html, status" in src,
          "the status is this engine's one advantage over Selenium")
    check("it merges in PAGE order", "sorted(outcomes, key=" in src)
    check("it masks credentials in an exception message",
          "_mask(str(e))" in src,
          "requests puts the full URL, query string included, into every "
          "connection error")
    check("every request is bounded", "REQUEST_TIMEOUT" in src)
    for flag in ("--cdp-endpoint", "--solve-captcha", "--fingerprint"):
        check("%s is refused rather than ignored" % flag,
              "_refuse(p, \"%s\"" % flag in src)

    # The flags it DOES share must mean the same thing as in the engines.
    shared = {"--url", "--pages", "--category", "--format", "--out",
              "--delay", "--retries", "--retry-delay", "--proxy",
              "--proxy-file", "--proxy-rotate", "--proxy-shuffle",
              "--proxy-block-retries", "--allow-empty", "--dump-html",
              "--mode", "--tags"}
    flags = set(_argparse_flags("http_scraper"))
    missing = shared - flags
    check("it carries the contract flags that apply to it", not missing,
          str(sorted(missing)))
    # And NOT the browser-only ones, beyond the four it refuses by name.
    for absent in ("--headless", "--headful", "--fp-tags", "--fp-country",
                   "--captcha-api", "--min-score"):
        check("%s is absent from the HTTP engine" % absent,
              absent not in flags,
              "a browser flag on a browserless engine is a lie")


def check_a_failed_run_still_leaves_something_machine_readable():
    """`<out>.last_attempt.json`, beside a sidecar that may describe good data.

    It is right that a FAILED run must write no `<out>.meta.json`: `save`
    leaves the previous good output in place, and a "failed" sidecar beside
    it would contradict it. The gap that left — a failed run told a caller
    nothing but an exit code — was raised by a third-party audit on
    2026-10-13 and is the half of that report which needed no argument.

    A separate NAME is what lets both facts coexist.
    """
    with tempfile.TemporaryDirectory() as tmp:
        prefix = os.path.join(tmp, "out")
        rows = [Product(sku="A", title="x", price=1.0)]
        rc = output_writer.finish_run(
            rows, prefix, "json", False, blocked=False,
            stop_reason="completed", pages_requested=1, pages_completed=1,
            start_url=LISTING_URL, final_url=LISTING_URL)
        equal("a good run exits 0", rc, 0)
        check("...and writes a sidecar",
              os.path.exists(prefix + ".meta.json"))
        check("...and a last_attempt beside it",
              os.path.exists(prefix + ".last_attempt.json"))

        rc = output_writer.finish_run(
            [], prefix, "json", False, blocked=True,
            stop_reason="blocked_challenge", pages_requested=1,
            pages_completed=0, start_url=LISTING_URL, final_url=LISTING_URL)
        check("a failed run does not exit 0", rc != 0)
        good = json.load(open(prefix + ".json", encoding="utf-8"))
        equal("the previous rows are untouched", len(good), 1)
        meta = json.load(open(prefix + ".meta.json", encoding="utf-8"))
        equal("the sidecar still describes the GOOD run", meta["status"],
              "complete")
        last = json.load(open(prefix + ".last_attempt.json", encoding="utf-8"))
        equal("the manifest describes the FAILED one", last["status"],
              "failed")
        equal("...and says why", last["stop_reason"], "blocked_challenge")


def check_pyproject_matches_the_files_on_disk():
    """`pyproject.toml` and `requirements*.txt` are kept in sync BY HAND.

    CI installs only `requirements.txt`, so a drift between the two goes
    unnoticed there — which is why it is checked here instead. Raised
    by a third-party audit on 2026-10-13 as "one authoritative definition,
    or a check that they have not diverged"; this is the second, because the
    two files are read by different tools and neither can be generated from
    the other without a build step this repo does not have.

    Three things are compared: every top-level module is declared, every
    declared module exists, and every engine's extra names the same pins its
    requirements file does.
    """
    text = open(os.path.join(HERE, "pyproject.toml"), encoding="utf-8").read()

    declared = set(re.findall(r'^\s*"([a-z_]+)",\s*$', text, re.M))
    on_disk = {os.path.basename(f)[:-3] for f in glob.glob(os.path.join(HERE, "*.py"))}
    on_disk -= {"smoke_test"}          # the suite ships in no wheel
    missing = sorted(on_disk - declared)
    check("every module on disk is in py-modules", not missing,
          "%s — setuptools refuses to guess among this many top-level "
          "modules, so an undeclared one is simply absent from an install"
          % missing)
    phantom = sorted(d for d in declared
                     if d not in on_disk and not d.startswith(("beautifulsoup",
                                                               "requests",
                                                               "playwright",
                                                               "selenium",
                                                               "pyppeteer")))
    check("every declared module exists", not phantom, str(phantom))

    for engine in ("playwright", "selenium", "puppeteer"):
        req = os.path.join(HERE, "requirements-%s.txt" % engine)
        if not os.path.exists(req):
            continue
        pins = {ln.split("#")[0].strip()
                for ln in open(req, encoding="utf-8")
                if ln.strip() and not ln.strip().startswith("#")}
        pins = {p for p in pins if p}
        for pin in pins:
            check("pyproject's [%s] extra carries %s" % (engine, pin),
                  pin in text,
                  "requirements-%s.txt pins it and the extra does not, so "
                  "`pip install .[%s]` installs something different from "
                  "what the README tells a user to run" % (engine, engine))

    core = {ln.split("#")[0].strip()
            for ln in open(os.path.join(HERE, "requirements.txt"), encoding="utf-8")
            if ln.strip() and not ln.strip().startswith("#")}
    for pin in {c for c in core if c}:
        check("pyproject's dependencies carry %s" % pin, pin in text)


def check_the_console_scripts_point_at_real_entry_points():
    """`pip install .` must give a command that exists.

    A `[project.scripts]` naming a function that is not there installs a
    console script that fails with ImportError on its first run — and
    nothing in a normal test run imports it, because every example in this
    repo invokes the modules as scripts.
    """
    text = open(os.path.join(HERE, "pyproject.toml"), encoding="utf-8").read()
    block = re.search(r"\[project\.scripts\]\n((?:[^\[]*\n)*)", text)
    check("there is a [project.scripts] table", block is not None)
    if not block:
        return
    entries = re.findall(r'^\s*[\w-]+\s*=\s*"([\w_]+):([\w_]+)"\s*$',
                         block.group(1), re.M)
    check("it names at least one command", bool(entries))
    for module, func in entries:
        path = os.path.join(HERE, module + ".py")
        check("%s.py exists for the console script" % module,
              os.path.exists(path))
        if not os.path.exists(path):
            continue
        tree = ast.parse(open(path, encoding="utf-8").read())
        names = {n.name for n in tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        check("%s defines %s()" % (module, func), func in names)
        # ...and the module is still runnable as a script, because that is
        # what the README, the workflows and the Dockerfile all use.
        src = open(path, encoding="utf-8").read()
        check("%s is still runnable as a script" % module,
              '__name__ == "__main__"' in src)


def check_every_cli_is_covered_by_the_help_check():
    """A new CLI that nothing runs `--help` on is a CLI nobody tested.

    `ci_checks.py --help-check` is what CI runs, and its list is written by
    hand. `http_scraper.py` was added to this repo on 2026-10-13 and the
    list is exactly the kind of thing that does not get updated with it.
    """
    sys.path.insert(0, os.path.join(HERE, ".github"))
    try:
        import ci_checks
    except ImportError as e:
        skip("ci_checks", str(e))
        return
    entry_points = set()
    for path in glob.glob(os.path.join(HERE, "*.py")):
        name = os.path.basename(path)
        if name in ("smoke_test.py",):
            continue
        src = open(path, encoding="utf-8").read()
        if "argparse.ArgumentParser(" in src and '__name__ == "__main__"' in src:
            entry_points.add(name)
    missing = sorted(entry_points - set(ci_checks.CLIS))
    check("every CLI in the repo is in ci_checks.CLIS", not missing,
          "%s — CI runs --help on that list and on nothing else" % missing)


def check_no_marker_fires_on_a_page_fetched_over_CDP():
    """The fixture that matters is the one fetched the way a run fetches.

    2Captcha's Scraping Browser ships an auto-solve extension that injects
    its own hunters into EVERY page it loads. Counted on a 101 KB listing
    pulled over `--cdp-endpoint` on 2026-10-13, holding 24 real product
    tiles:

        chrome-extension:// scripts      16
        `captcha` (bare)                 21
        `recaptcha` (bare)                2
        `cf-turnstile`                    1
        `<captcha-widgets>`               1
        `recaptcha/api.js`                0   <- what the SITE would ship
        `www.google.com/recaptcha`        0

    This repo carried a bare `recaptcha` marker until that page existed, and
    it FIRED on it. Nothing broke, because tiles are checked before markers
 — but a page with no tiles, an exhausted tag facet say, would have
    been reported as a challenge over CDP: exit 3 for a correct answer.

    The claim "no marker fires on a good page" had been true of every
    capture this repo had, and every one of them was fetched LOCALLY. That
    is the guard passing for the wrong reason, and the rule is to commit a
    CDP-fetched fixture for exactly this.
    """
    check("the fixture really carries the extension's injections",
          CDP_PAGE_HTML.count("chrome-extension://") >= 10,
          str(CDP_PAGE_HTML.count("chrome-extension://")))
    check("...including the bare words a loose marker would match",
          CDP_PAGE_HTML.count("recaptcha") >= 2
          and "cf-turnstile" in CDP_PAGE_HTML)
    check("...and the empty mount point it also injects",
          "<captcha-widgets" in CDP_PAGE_HTML)
    check("...and it is a GOOD page: real product tiles on it",
          product_parser.tile_count(CDP_PAGE_HTML) >= 2)

    equal("no marker fires on it",
          product_parser.detect_bot_challenge(CDP_PAGE_HTML), None)
    equal("so it classifies as content",
          page_flow.classify(CDP_PAGE_HTML, 200), "content")

    # And the same page with its tiles taken away must STILL be clean —
    # which is the case that would have exited 3.
    tileless = CDP_PAGE_HTML.replace('<li class="c-product__item',
                                     '<li class="x')
    equal("...and still clean once the tiles are gone",
          product_parser.detect_bot_challenge(tileless), None)

    # The narrowing must not have blinded it: a real loader is still caught.
    real = tileless.replace(
        "</head>",
        '<script src="https://www.google.com/recaptcha/api.js"></script>'
        "</head>", 1)
    equal("a REAL reCAPTCHA loader is still detected",
          page_flow.classify(real, 200), "challenge")

    # The marker set must score zero WITHOUT any extension strip, or
    # the strip is load-bearing and the next marker added inherits the hole.
    check("this repo carries no chrome-extension strip to lean on",
          "chrome-extension" not in open(
              os.path.join(HERE, "product_parser.py"), encoding="utf-8"
          ).read().split("BOT_CHALLENGE_MARKERS")[1][:2000].replace(
              "chrome-extension://…/content", ""),
          "if a strip is added, this check stops proving anything")


def check_a_url_from_the_environment_does_not_block_the_builders():
    """`KOSE_URL` in `.env` made `--tags` and `--category` unusable.

    `env_config.apply` fills only UNSET values, so after it runs `args.url`
    is the same whether the user typed one or `.env` supplied one. Every CLI
    here then refused `--tags` with "--url already names what to fetch" —
    for anyone who had set the variable that `.env.example` ships and the
    README recommends. The two flags did not work in the setup this repo
    tells people to create, and had not since the repo was written.

    Found on 2026-10-13 while regenerating the sample output, which is the
    only reason it surfaced: every example in the README passes `--url`.
    """
    for module in list(ENGINES) + ["http_scraper"]:
        path = os.path.join(HERE, module + ".py")
        if not os.path.exists(path):
            continue
        src = open(path, encoding="utf-8").read()
        check("%s captures what the user typed before env_config runs"
              % module, "typed_url = args.url" in src)
        check("%s: the --url/--tags conflict is judged on that" % module,
              "if typed_url and args.tags:" in src,
              "judging it on args.url means an environment variable reads "
              "as a flag the user passed")
        check("%s: and so is the builder" % module,
              "if not typed_url and args.tags:" in src)
        # The capture has to come BEFORE the environment is applied, or it
        # captures the same filled-in value and nothing changes. Compared
        # against the CALL, not the string: the first version of this check
        # matched the word inside its own explanatory comment and reported
        # every engine broken (a check that matches a comment rather
        # than the code).
        check("%s: captured before env_config.apply(args) runs" % module,
              src.index("typed_url = args.url")
              < src.index("env_config.apply(args)"),
              "captured after apply() it is the same value")


CHECKS = [v for k, v in sorted(globals().items()) if k.startswith("check_")]


def main():
    global VERBOSE
    parser = argparse.ArgumentParser(description="kose-scraper offline suite")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    VERBOSE = args.verbose

    global _TREE_BEFORE
    _TREE_BEFORE = _tree_state()

    for fn in CHECKS:
        if VERBOSE:
            print("\n== %s" % fn.__name__)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 — a broken check is a failure
            import traceback
            FAILURES.append("%s raised %s: %s" % (fn.__name__, type(e).__name__, e))
            print("  ERROR %s raised %s: %s" % (fn.__name__, type(e).__name__, e))
            if VERBOSE:
                traceback.print_exc()

    print("\n%d checks passed, %d failed, %d group(s) skipped."
          % (PASSED, len(FAILURES), len(SKIPS)))
    for line in SKIPS:
        print("  skipped: %s" % line)
    if FAILURES:
        print("\nFailures:")
        for line in FAILURES:
            print("  - %s" % line)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
