// Input formats follow the clients in webmirage/platforms and platform_worker.
// Examples are instructions only; never prefill a credential input.
export interface CredentialFieldGuide {
  name: string
  example: string
  requirement: string
  hint: string
  configField?: string
  valueOnly?: boolean
  valueName?: string
}

export const credentialFields: Record<string, CredentialFieldGuide> = {
  twitter_auth_token: {
    valueOnly: true, valueName: 'auth_token', name: 'auth_token', example: '粘贴 auth_token 的 Value', requirement: '登录必需',
    hint: '只填写 auth_token 的值。auth_token 与 ct0 应来自同一浏览器、同一次登录；两个字段分别填写。',
  },
  twitter_ct0: {
    valueOnly: true, valueName: 'ct0', name: 'ct0', example: '粘贴 ct0 的 Value', requirement: '登录必需',
    hint: '只填写 ct0 的值。这是请求校验 Cookie，更新登录时请与 auth_token 一起核对。',
  },
  xueqiu_cookie: {
    name: 'xq_a_token', example: 'xq_a_token=你的值; 其他Cookie名称=对应值', requirement: '登录态需包含',
    hint: '完整导入会替换整段雪球 Cookie；请包含 xq_a_token，多个键值对用分号分隔。仅更换个别值时请选择“逐项填写”。',
  },
  xianyu_cookie: {
    name: '_m_h5_tk、_m_h5_tk_enc、cookie2、unb', example: '_m_h5_tk=你的值_时间戳; _m_h5_tk_enc=配对值; cookie2=会话值; unb=用户ID', requirement: '必填',
    hint: '完整导入必须包含这四项且值非空。_m_h5_tk 保留完整“_时间戳”后缀，与 _m_h5_tk_enc、cookie2 使用同一次登录的值；其他会话 Cookie 建议一并保留。保存后仍需检测确认。',
  },
  xianyu_user_id: {
    valueOnly: true, valueName: 'unb', name: 'unb（Cookie 中的用户 ID）', example: '粘贴 unb 的 Value', requirement: '可选',
    hint: '通常留空，客户端从 unb 读取用户 ID。如果以前单独设置过此覆盖项，换账号时请与新的 unb 同步更新；只填用户 ID 的值。',
  },
  reddit_cookie: {
    name: 'reddit_session 及同次会话 Cookie', example: 'reddit_session=你的值; token_v2=对应值; csrf_token=对应值', requirement: '登录态需包含',
    hint: '导入模式会替换已有的整段 Reddit Cookie。填写包含 reddit_session 的完整键值对，建议一并保留 token_v2、csrf_token、session_tracker、loid、edgebucket、csv 等同次会话项。多个项用分号分隔，保留原有编码；仅导入 reddit.com 域的 Cookie。',
  },
  reddit_session: {
    valueOnly: true, valueName: 'reddit_session', name: 'reddit_session', example: '只粘贴 reddit_session 的 Value（值）', requirement: '登录必填 · 只填值', configField: 'reddit_cookie',
    hint: '直接粘贴浏览器 Value 列的完整内容，保留原有编码。系统自动补上名称和等号，其他已有 Cookie 会保留。单独更新后仍失败时，可切换“导入完整 Cookie”，保留同次浏览器会话的其他字段后复测。',
  },
  github_tokens: {
    valueOnly: true, name: 'Personal access token（个人访问令牌）', example: '粘贴一个 GitHub Token 的完整值', requirement: '可选',
    hint: '填写一个完整 Token 值，按需要授予只读权限。当前表单会用这一个 Token 替换文件中的 Token 列表；留空保留原配置。公开接口可匿名调用，但受匿名限额限制。',
  },
}

export const cookieForms: Record<string, { primary: string[]; optional: string[] }> = {
  reddit: { primary: ['reddit_session'], optional: ['token_v2', 'csrf_token', 'session_tracker', 'loid', 'edgebucket', 'csv'] },
  xueqiu: { primary: ['xq_a_token'], optional: ['acw_tc', 'device_id'] },
  xianyu: { primary: ['_m_h5_tk', '_m_h5_tk_enc', 'cookie2', 'unb'], optional: ['sgcookie', '_tb_token_', 't', 'xianyu_user_id'] },
}

const cookieDetails: [string, string, string, string][] = [
  ['token_v2', 'reddit_cookie', '会话补充 · 按需填写', '浏览器中如存在 token_v2，请复制同次登录的完整 Value，保留编码；尚未确认它是所有只读接口的必需项。'],
  ['csrf_token', 'reddit_cookie', '会话补充 · 按需填写', '复制同次登录的 csrf_token 值。当前只读客户端不会据此添加 CSRF 请求头，不将它视为通用必填项。'],
  ['session_tracker', 'reddit_cookie', '会话补充 · 按需填写', '如存在，复制同次浏览器会话的 session_tracker 完整值。留空保留已有值。'],
  ['loid', 'reddit_cookie', '会话补充 · 按需填写', '如存在，复制同次浏览器会话的 loid 完整值，保留编码。留空保留已有值。'],
  ['edgebucket', 'reddit_cookie', '会话补充 · 按需填写', '如存在，复制同次浏览器会话的 edgebucket 值。留空保留已有值。'],
  ['csv', 'reddit_cookie', '会话补充 · 按需填写', '如存在，复制同次浏览器会话的 csv 值。留空保留已有值。'],
  ['xq_a_token', 'xueqiu_cookie', '核心登录项', '复制 xq_a_token 的完整 Value，系统自动拼接名称和等号；其他已有 Cookie 保留。'],
  ['acw_tc', 'xueqiu_cookie', '可选', '按需更新浏览器中的 acw_tc 会话值，留空保留原值。'],
  ['device_id', 'xueqiu_cookie', '可选', '按需更新同一次浏览器会话中的 device_id 值，留空保留原值。'],
  ['_m_h5_tk', 'xianyu_cookie', '必填', '名称开头有下划线。复制包含“_时间戳”的完整 Value；须与 _m_h5_tk_enc、cookie2 一起填写，来自同次登录。'],
  ['unb', 'xianyu_cookie', '必填', '复制 unb 的 Value（用户 ID）。如果以前设置过“用户 ID 覆盖”，请在选填区域同步更新该覆盖项。'],
  ['_m_h5_tk_enc', 'xianyu_cookie', '必填', '复制与 _m_h5_tk 配对、来自同次浏览器登录的完整 Value，只填写值。'],
  ['cookie2', 'xianyu_cookie', '必填', '复制同次登录的 cookie2 会话值，只填写值；更新时必须与签名 token 配套提交。'],
  ['sgcookie', 'xianyu_cookie', '可选', '按需复制同次登录的 sgcookie 值，保留原有编码。'],
  ['_tb_token_', 'xianyu_cookie', '可选', '按需复制同次登录的 _tb_token_ 值，名称两端都有下划线。'],
  ['t', 'xianyu_cookie', '可选', '按需复制同次登录中名称为 t 的 Cookie 值，留空保留原值。'],
]
for (const [name, configField, requirement, hint] of cookieDetails) {
  credentialFields[name] = { name, configField, requirement, hint, valueOnly: true, valueName: name,
    example: `只粘贴 ${name} 的 Value（值）` }
}

export const credentialSources: Record<string, { url: string; domain: string; instruction: string; note?: string }> = {
  twitter: { url: 'https://x.com/', domain: 'x.com', instruction: '在已登录页面按 F12 → Application（应用）→ Cookies，选择 x.com，分别找到 auth_token 和 ct0，复制各自的 Value（值）。' },
  xueqiu: { url: 'https://xueqiu.com/', domain: 'xueqiu.com', instruction: '在已登录页面按 F12 → Application（应用）→ Cookies，选择 xueqiu.com，找到 xq_a_token，直接复制 Value（值）到同名输入框。' },
  xianyu: { url: 'https://www.goofish.com/', domain: 'goofish.com', instruction: '在已登录页面按 F12 → Application（应用）→ Cookies，选择 goofish.com，找到 _m_h5_tk、_m_h5_tk_enc、cookie2、unb，分别复制同一次登录的完整 Value（值）到同名输入框；四项必填，其他会话项可选。' },
  reddit: { url: 'https://www.reddit.com/', domain: 'reddit.com', instruction: '在已登录页面按 F12 → Application（应用）→ Cookies，选择 reddit.com 或 www.reddit.com，找到 reddit_session，复制完整 Value（值）；展开选填区域可填写 token_v2、csrf_token、session_tracker、loid、edgebucket、csv。请使用同一次登录的值，不要混入 Google 等其他域的 Cookie。如需保留所有站点会话项，选择“导入完整 Cookie”，从浏览器该站请求的 Cookie 标头复制整段。', note: '登录必填项为 reddit_session；补充会话项可逐项填写或随完整 Cookie 导入，尚未验证的字段不统一设为必填。403 本身不能确认缺项或凭证失效；更新后分别检查“社区帖子”和“帖子搜索”。' },
  github: { url: 'https://github.com/settings/tokens', domain: 'GitHub Token 设置', instruction: '在 GitHub 个人设置的 Developer settings → Personal access tokens 中创建或管理个人访问令牌，复制生成的完整 Token 值。' },
}
