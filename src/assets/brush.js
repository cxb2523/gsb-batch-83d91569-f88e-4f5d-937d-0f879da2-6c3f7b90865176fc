(function () {
  "use strict";
  if (typeof echarts === "undefined") return;

  function num(v) {
    if (v == null) return null;
    if (typeof v === "object" && "value" in v) v = v.value;
    return (typeof v === "number" && isFinite(v)) ? v : null;
  }

  function rangeBrush(containerId, label, unit) {
    var el = document.getElementById(containerId);
    if (!el || !el.parentNode) return;
    var wrap = el.parentNode;
    if (wrap.style.position !== "relative" && wrap.style.position !== "absolute") {
      wrap.style.position = "relative";
    }
    var band = document.createElement("div");
    band.className = "brush-band";
    var tip = document.createElement("div");
    tip.className = "brush-tip";
    wrap.appendChild(band);
    wrap.appendChild(tip);

    var dragging = false, x0 = 0, x1 = 0, SLIDER_H = 44;

    function rect() { return el.getBoundingClientRect(); }
    function localX(e) { return e.clientX - rect().left; }
    function localY(e) { return e.clientY - rect().top; }

    function hide() { band.style.display = "none"; tip.style.display = "none"; }

    function offsetInWrap() {
      var wr = wrap.getBoundingClientRect(), er = rect();
      return { ox: er.left - wr.left, oy: er.top - wr.top };
    }

    function drawBand(a, b) {
      var o = offsetInWrap();
      band.style.display = "block";
      band.style.left = (o.ox + Math.min(a, b)) + "px";
      band.style.top = o.oy + "px";
      band.style.width = Math.abs(b - a) + "px";
      band.style.height = el.clientHeight + "px";
    }

    function idxAt(x) {
      var inst = echarts.getInstanceByDom(el);
      if (!inst) return null;
      var o = inst.getOption();
      var cats = (o.xAxis && o.xAxis[0] && o.xAxis[0].data) || [];
      if (!cats.length) return null;
      /* 必须用 gridIndex 作 finder：实测 convertFromPixel({xAxisIndex:0}) 返回 null，
         拿不到索引就会静默失败（表现为拖得出来、但不显示合计）。 */
      var p = inst.convertFromPixel({ gridIndex: 0 }, [x, 0]);
      if (!p || !isFinite(p[0])) return null;
      return Math.max(0, Math.min(cats.length - 1, Math.round(p[0])));
    }

    function compute(a, b) {
      var inst = echarts.getInstanceByDom(el);
      if (!inst) return;
      var o = inst.getOption();
      var cats = (o.xAxis && o.xAxis[0] && o.xAxis[0].data) || [];
      var i0 = idxAt(Math.min(a, b)), i1 = idxAt(Math.max(a, b));
      if (i0 == null || i1 == null || !cats.length) return;
      var sum = 0, hit = 0;
      (o.series || []).forEach(function (s) {
        if (s.type !== "bar") return;          // 只要柱状：排除折线（指数点位、累计净流入）
        var d = s.data || [];
        for (var i = i0; i <= i1; i++) {
          var v = num(d[i]);
          if (v != null) { sum += v; hit++; }
        }
      });
      var span = i1 - i0 + 1;
      var txt = label + "合计 " + sum.toFixed(1) + " 亿元";
      /* 单位按图区分：分钟图写「分钟」，日度图写「交易日」，不写笼统的「项」 */
      if (span > 1) txt += "｜" + cats[i0] + " ~ " + cats[i1] + "（" + span + " " + (unit || "项") + "）";
      else txt += "｜" + cats[i0];

      var o2 = offsetInWrap();
      tip.textContent = txt;
      tip.style.display = "block";
      tip.style.left = (o2.ox + (a + b) / 2) + "px";
      tip.style.top = (o2.oy + 4) + "px";
    }

    el.addEventListener("mousedown", function (e) {
      if (e.button !== 0 && e.button !== 2) return;    // 只认左键 / 右键
      if (localY(e) > el.clientHeight - SLIDER_H) return;  // 底部是 dataZoom 滑块，别抢
      dragging = true;
      x0 = x1 = localX(e);
      drawBand(x0, x1);
      tip.style.display = "none";
      e.preventDefault();
    }, true);
    el.addEventListener("contextmenu", function (e) { e.preventDefault(); });

    window.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      x1 = localX(e);
      drawBand(x0, x1);
    }, true);
    window.addEventListener("mouseup", function (e) {
      if (!dragging) return;
      dragging = false;
      x1 = localX(e);
      if (Math.abs(x1 - x0) < 4) { hide(); return; }   // 视作单击，清除
      compute(x0, x1);
    }, true);
  }

  /* 图表实例在前面各段里同步创建，这里直接绑定即可 */
  rangeBrush("chart", "成交额", "分钟");
  rangeBrush("chartDAmt", "成交额", "交易日");
  rangeBrush("chartDNf", "净流入", "交易日");
  rangeBrush("chartBroad", "净流入", "交易日");
})();
