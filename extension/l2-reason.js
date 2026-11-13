// 真实事件层（L2，chrome.debugger）不可用的分类与处理提示。
//
// 存在理由：降级发生时，调用方以前只看到一次「点了没反应」，分不清是页面不认，
// 还是真实事件这条路根本没走通。而这两种情况的下一步动作完全不同——前者该换目标
// 或先 wait，后者该让用户去开开关、关 DevTools。把「为什么没接上」写成结构化的
// 一档，回执里就有一句能照着做的话，而不是让 agent 换着花样重试。
//
// 纯字符串/纯数据，不碰任何 chrome API —— 这样 `npm test` 能直接把四类都跑到，
// 不必开真 Chrome。文案只在这里写一次：扩展回执、MCP 错误提示都从这儿取。
// 两边各写一份的话，同一种失败在两条通道上会慢慢说出不一样的话。

export const L2_CODE = {
  disabled: 'NEEDS_L2',
  busy: 'L2_BUSY',
  protected: 'L2_PROTECTED',
  attach: 'L2_ATTACH',
};

// label 是回执里那一行的分类词（「没接上 ✗ —— 开关被关」），
// title 是完整的一句话，hint 是给调用方的下一步动作。
export const L2_REASONS = {
  disabled: {
    label: '开关被关',
    title: '高保真模式被关掉了',
    hint: '让用户点开 huashu-chrome 扩展图标（或侧栏），在「高保真模式」一栏打开开关，然后重试。',
  },
  busy: {
    label: '调试器被占用',
    title: '这个标签页已经被另一个调试器占用',
    hint: '多半是用户自己开着 DevTools（一个标签页只允许一个调试器）。让用户关掉 DevTools 后重试；在那之前普通事件仍然可用。',
  },
  protected: {
    label: '浏览器保护页',
    title: '浏览器保护页不允许调试器接入',
    hint: 'chrome://、扩展页、devtools:// 这类页面打不到真实事件。换一个普通网页操作；这一步只能由用户手动完成。',
  },
  attach: {
    label: '接入失败',
    title: '真实事件层没能接上这个标签页',
    hint: '稍后重试一次；持续出现就重启 Chrome，或在 chrome://extensions 里重新加载扩展。普通事件仍然可用。',
  },
};

export const L2_CODES = new Set(Object.values(L2_CODE));

// chrome.debugger.attach 的报错 → 四档里的哪一档。
// 匹配不上的一律归到「接入失败」：宁可给出泛化的处理提示，也不要把它吞成
// 「页面没反应」——那正是这次要修的那类静默失败。
export function classifyAttachError(message) {
  const m = String(message || '');
  if (/Another debugger is already attached|already attached to this (tab|target)/i.test(m)) return 'busy';
  if (/Cannot access|Cannot attach to this target|chrome:\/\/|chrome-extension:\/\/|devtools:\/\/|protected/i.test(m)) return 'protected';
  return 'attach';
}

// attach 成功之后，命令途中通道被掐断（用户点了黄条上的取消、标签页关了、
// 后台标签页的调试会话被浏览器收走）。这在调用方看来和「没接上」是同一件事：
// 真实事件没有送达，不能把这次操作说成真实事件的结果。
export function isL2LayerLost(message) {
  return /Detached while handling command|Not attached to (the )?(page|target)|Target closed|No target with given id|Session (closed|not found)/i.test(String(message || ''));
}

export function l2ReasonInfo(reason) {
  const key = L2_REASONS[reason] ? reason : 'attach';
  const r = L2_REASONS[key];
  return { reason: key, code: L2_CODE[key], label: r.label, title: r.title, hint: r.hint };
}

// 只认「层不可用」这一类错误。同一个 L2Unavailable 类还用来表达「元素没找到」
// （REF_NOT_FOUND）和「表达式执行失败」（INTERNAL），那些是动作的问题，不是层的问题，
// 调用方不该因此收到「真实事件没接上」的结论。
export function isL2Unavailable(e) {
  return !!e && L2_CODES.has(e.code);
}

// 错误 → 分类。优先认显式的 reasonKey（cdp 造错误时带上的），
// 退而按错误码认——老的回执里只有 code 的路径也能落到对的那一档。
export function reasonOfError(e) {
  if (!e) return null;
  if (L2_REASONS[e.reasonKey]) return e.reasonKey;
  for (const [key, code] of Object.entries(L2_CODE)) if (code === e.code) return key;
  return null;
}

// ---------- 回执 ----------
//
// 「这次到底有没有接上」必须每次都说，所以它不挂在成功/失败分支里，而是
// 按三层状态直接渲染：接上了、没接上（带分类与处理）、压根没尝试（不出声）。
//
// l2 报告的字段约定（background 组装）：
//   attempted  这次是否真的尝试接入真实事件层
//   used       调用结束时是否经真实事件执行
//   degraded   是否降级（真实事件没走通）
//   reason     disabled | busy | protected | attach
//   code       回执里给 agent 看的错误码
//   title/detail/hint  原因与处理提示
//   phase      attach（没接上）| dispatch（操作途中断开）
//   auto       是不是「普通事件零证据 → 自动升级」这条路走到的
export function l2Lines(l2) {
  if (!l2?.attempted) return [];
  if (l2.used) {
    return ['真实事件层：已接入 ✓（下面的效果就是真实事件送达的结果）'];
  }
  if (!l2.degraded) return [];
  const info = l2ReasonInfo(l2.reason);
  const lines = [
    `真实事件层：没接上 ✗ —— ${info.label}（${l2.code || info.code}）`,
    `   原因：${l2.title || info.title}${l2.detail ? `（${l2.detail}）` : ''}`,
    `   处理：${l2.hint || info.hint}`,
  ];
  if (l2.phase === 'dispatch') {
    lines.push('   注意：真实事件是在操作途中断开的，可能已经有一部分送达——先看下面的效果证据，别直接重试。');
  } else {
    lines.push(l2.auto
      ? '   普通事件已经照常试过一次（结果见下），真实事件没能接上。'
      : '   这次只走了普通事件（结果见下），真实事件没能接上。');
  }
  return lines;
}

// act 的每一步只印一行：接上了就标一句，没接上就把分类压成一句塞进 ✅/⏸ 后面。
// 批处理里铺开三行「原因/处理」会把每一步的结论淹掉——单发的 click/type 才用 l2Lines。
export function l2Tag(l2) {
  if (!l2?.attempted) return '';
  if (l2.used) return '真实事件 ✓';
  if (!l2.degraded) return '';
  const info = l2ReasonInfo(l2.reason);
  return `真实事件层没接上：${info.label}（${l2.code || info.code}）`;
}

