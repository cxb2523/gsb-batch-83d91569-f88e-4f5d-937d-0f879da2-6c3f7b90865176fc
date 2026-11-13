"""Persian texts and inline keyboards. HTML parse mode; every dynamic value escaped.

Callback data is short, versioned and parsed against an allowlist. It carries
only opaque tokens (a run-ID prefix, a page, an index, a one-time confirmation
nonce); event content is always looked up server-side.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .services import PlannedFeature, SourceView

PREFIX = 'gr1'
MAIN = f'{PREFIX}:menu'
HELP = f'{PREFIX}:help'
ABOUT = f'{PREFIX}:about'
CREATOR_GITHUB = 'https://github.com/MohebaliDesign'
REPOSITORY = 'https://github.com/MohebaliDesign/GatherRadar'
SOURCES = f'{PREFIX}:src:list:'          # + page
SOURCE = f'{PREFIX}:src:show:'           # + source id
SOON = f'{PREFIX}:soon:'                 # + PlannedFeature value
CRAWL_ALL = f'{PREFIX}:crawl:all'
SELECT = f'{PREFIX}:sel:'                # + page | t:<id>:<page> | all:<page> | clr:<page> | ok
GO = f'{PREFIX}:go:'                     # + one-time nonce
NO = f'{PREFIX}:no:'                     # + one-time nonce
JOB, JOB_CANCEL = f'{PREFIX}:job', f'{PREFIX}:jobx'
OUTPUTS = f'{PREFIX}:out'
EXCEL = f'{PREFIX}:xl:'                  # + run token
EVENTS = f'{PREFIX}:ev:'                 # + run token:kind:page
EVENT = f'{PREFIX}:ed:'                  # + run token:kind:index
RUNS = f'{PREFIX}:runs:'                 # + page
RUN = f'{PREFIX}:run:'                   # + run token
SETTINGS = f'{PREFIX}:set'
MANAGE = f'{PREFIX}:sm:home'
MANAGE_LIST = f'{PREFIX}:sm:ls:'         # + filter (a active, d disabled, x archived, l listed) : page
MANAGE_VIEW = f'{PREFIX}:sm:v:'          # + source id
MANAGE_ACT = f'{PREFIX}:sm:act:'         # + op (e enable, d disable, x archive, r restore) : source id
MANAGE_OK = f'{PREFIX}:sm:ok:'           # + one-time nonce
MANAGE_NO = f'{PREFIX}:sm:no:'           # + one-time nonce
ADD = f'{PREFIX}:sm:add'                 # choose a type; + ':i' / ':w' starts that conversation
SAVE = f'{PREFIX}:sm:save:'              # + nonce : a (save active) | p (save paused)
ADD_CANCEL = f'{PREFIX}:sm:cx'
ADD_BACK = f'{PREFIX}:sm:bk'
_ID = r'[a-z0-9_]{1,40}'
_TOKEN = r'[A-Za-z0-9_-]{4,12}'
_CALLBACK = re.compile(
    rf'{PREFIX}:(?:(?P<menu>menu)|(?P<help>help)|(?P<about>about)|src:list:(?P<page>[0-9]{{1,3}})'
    rf'|src:show:(?P<source>{_ID})|soon:(?P<soon>[a-z_]{{1,20}})'
    rf'|(?P<crawl_all>crawl:all)'
    rf'|sel:(?:(?P<sel_page>[0-9]{{1,3}})|t:(?P<sel_toggle>{_ID}):(?P<sel_toggle_page>[0-9]{{1,3}})'
    rf'|all:(?P<sel_all>[0-9]{{1,3}})|clr:(?P<sel_clear>[0-9]{{1,3}})|(?P<sel_ok>ok))'
    rf'|go:(?P<go>[A-Za-z0-9]{{8,16}})|no:(?P<no>[A-Za-z0-9]{{8,16}})'
    rf'|(?P<job_cancel>jobx)|(?P<job>job)|(?P<outputs>out)'
    rf'|xl:(?P<excel>{_TOKEN})|ev:(?P<ev_run>{_TOKEN}):(?P<ev_kind>[ar]):(?P<ev_page>[0-9]{{1,3}})'
    rf'|ed:(?P<ed_run>{_TOKEN}):(?P<ed_kind>[ar]):(?P<ed_index>[0-9]{{1,4}})'
    rf'|runs:(?P<runs>[0-9]{{1,2}})|run:(?P<run>{_TOKEN})|(?P<settings>set)'
    rf'|sm:(?:(?P<sm_home>home)|ls:(?P<sm_filter>[adxl]):(?P<sm_page>[0-9]{{1,3}})|v:(?P<sm_view>{_ID})'
    rf'|act:(?P<sm_op>[edxr]):(?P<sm_target>{_ID})|ok:(?P<sm_ok>[A-Za-z0-9]{{8,16}})'
    rf'|no:(?P<sm_no>[A-Za-z0-9]{{8,16}})|add:(?P<sm_add>[iw])|(?P<sm_addmenu>add)'
    rf'|save:(?P<sm_save>[A-Za-z0-9]{{8,16}}):(?P<sm_mode>[ap])|(?P<sm_cancel>cx)|(?P<sm_back>bk)))')
PAGE_SIZE = 8
EVENTS_PER_PAGE = 5
RUNS_PER_PAGE = 6
MESSAGE_LIMIT = 3900  # below Telegram's 4,096-character text limit

FEATURES = {
    PlannedFeature.CRAWL_ALL: '🔄 کرال همه منابع',
    PlannedFeature.SELECT_SOURCES: '🎯 انتخاب منابع',
    PlannedFeature.MANAGE_SOURCES: '📋 مدیریت منابع',
    PlannedFeature.EXPORTS: '📊 دریافت خروجی',
    PlannedFeature.RUNS: '🕘 آخرین اجراها',
    PlannedFeature.SETTINGS: '⚙️ تنظیمات',
}
UNFINISHED: tuple = ()  # every menu entry is implemented; Settings is read-only and says so
KINDS = {'instagram': 'اینستاگرام', 'website': 'وب‌سایت'}
REASONS = {'robots': 'فایل robots.txt سایت اجازه جمع‌آوری به GatherRadar نمی‌دهد',
           'terms': 'شرایط استفاده سایت اجازه جمع‌آوری نمی‌دهد',
           'owner': 'توسط شما غیرفعال شده است',
           'unsupported': 'ساختار این وب‌سایت هنوز توسط GatherRadar پشتیبانی نمی‌شود'}
STAGES = {'queued': 'در صف', 'starting': 'آماده‌سازی', 'collecting': 'جمع‌آوری از منابع',
          'analyzing': 'تحلیل و استخراج رویدادها', 'persisting': 'ذخیره در پایگاه داده',
          'exporting': 'ساخت خروجی Excel', 'done': 'پایان', 'interrupted': 'متوقف‌شده'}
JOB_STATUS = {'running': 'در حال اجرا', 'cancelling': 'در حال توقف (پس از پایان منبع فعلی)',
              'success': 'موفق', 'partial': 'نیمه‌موفق', 'failed': 'ناموفق', 'cancelled': 'لغو شد',
              'error': 'خطا', 'interrupted': 'قطع‌شده'}
SOURCE_STATUS = {'success': '✅', 'partial': '⚠️', 'failed': '❌'}
MODES = {'refresh': 'کرال زنده', 'stored_sync': 'بازپخش داده ذخیره‌شده', 'incomplete': 'ناتمام'}
CATEGORIES = {'performance': 'اجرا', 'workshop': 'کارگاه', 'exhibition': 'نمایشگاه', 'concert': 'کنسرت',
              'festival': 'جشنواره', 'conference': 'همایش', 'talk': 'نشست', 'meetup': 'دورهمی',
              'screening': 'اکران', 'market': 'بازارچه', 'tour': 'تور'}

NOT_YET = 'این قابلیت در مرحله بعد فعال می‌شود.'
PRIVATE_ONLY = 'این ربات خصوصی است و فقط به مالک خود پاسخ می‌دهد.'
INVALID = 'این گزینه دیگر معتبر نیست. منوی اصلی را دوباره باز کنید.'
ERROR = 'خطایی رخ داد و جزئیات آن در گزارش محلی ثبت شد. دوباره تلاش کنید.'
BUSY = 'یک اجرا در جریان است؛ تا پایان آن اجرای جدید شروع نمی‌شود.'
BOOTSTRAP = ('مالک ربات هنوز تنظیم نشده است.\n'
             'برای دیدن شناسه عددی خود دستور /whoami را بفرستید.')


def e(value: object) -> str:
    """HTML-escape any value that came from configuration, a source or a user."""
    return html.escape(str(value), quote=False)


def parse_callback(data: str | None) -> dict[str, str] | None:
    if not isinstance(data, str) or len(data.encode()) > 64:
        return None
    match = _CALLBACK.fullmatch(data)
    if match is None:
        return None
    return {key: value for key, value in match.groupdict().items() if value is not None}


def clip(text: str, limit: int) -> str:
    text = ' '.join(str(text).split()) if '\n' not in str(text) else str(text).strip()
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def fit(text: str) -> str:
    """Keep a message under Telegram's limit without breaking an HTML tag."""
    if len(text) <= MESSAGE_LIMIT:
        return text
    cut = text[:MESSAGE_LIMIT]
    cut = cut[:cut.rfind('\n')] if '\n' in cut else cut
    return cut + '\n…'


def persian(value: object) -> str:
    return str(value).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))


def jalali(value: str | date | None) -> str:
    if not value:
        return ''
    from ..review.serialization import jalali as to_jalali
    return to_jalali(date.fromisoformat(value) if isinstance(value, str) else value)


def clock(value: str | None) -> str:
    return persian(time.fromisoformat(value).strftime('%H:%M')) if value else ''


def when(value: datetime | None) -> str:
    if value is None:
        return 'نامشخص'
    from zoneinfo import ZoneInfo
    local = value.astimezone(ZoneInfo('Asia/Tehran'))
    return f'{jalali(local.date())}، {persian(local.strftime("%H:%M"))}'


# -- durations -----------------------------------------------------------------
def duration(seconds: float | None) -> str:
    """Actual elapsed time in Persian: «۲ دقیقه و ۱۸ ثانیه»."""
    total = max(0, int(seconds or 0))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = []
    if hours:
        parts.append(f'{persian(hours)} ساعت')
    if minutes:
        parts.append(f'{persian(minutes)} دقیقه')
    if secs and not hours or not parts:
        parts.append(f'{persian(secs)} ثانیه')
    return ' و '.join(parts)


def eta_range(low: float, high: float) -> str:
    """A bounded, honest range in whole minutes (never a percentage)."""
    if high < 60:
        return 'کمتر از یک دقیقه'
    lo, hi = max(1, int(low // 60)), max(1, -(-int(high) // 60))
    return f'حدود {persian(lo)} دقیقه' if lo >= hi else f'حدود {persian(lo)} تا {persian(hi)} دقیقه'


NO_ESTIMATE = '⌛ هنوز داده کافی برای تخمین زمان باقی‌مانده نداریم.'
SPINNER = ('◐', '◓', '◑', '◒')


# -- main menu and help --------------------------------------------------------
def main_text() -> str:
    return ('<b>📡 به GatherRadar خوش آمدید</b>\n'
            'از اینجا می‌توانید رویدادها را از منابع منتخب جمع‌آوری کنید، منابع خود را مدیریت کنید '
            'و نتایج را به‌صورت Excel یا فهرست فارسی ببینید.\n\n'
            'برای شروع، یکی از گزینه‌های زیر را انتخاب کنید.')


def main_keyboard(active_job: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if active_job:
        rows.append([InlineKeyboardButton('⏳ وضعیت اجرای جاری', callback_data=JOB)])
    rows += [
        [InlineKeyboardButton(FEATURES[PlannedFeature.CRAWL_ALL], callback_data=CRAWL_ALL),
         InlineKeyboardButton(FEATURES[PlannedFeature.SELECT_SOURCES], callback_data=SELECT + '0')],
        [InlineKeyboardButton(FEATURES[PlannedFeature.MANAGE_SOURCES], callback_data=MANAGE),
         InlineKeyboardButton(FEATURES[PlannedFeature.EXPORTS], callback_data=OUTPUTS)],
        [InlineKeyboardButton(FEATURES[PlannedFeature.RUNS], callback_data=RUNS + '0'),
         InlineKeyboardButton('⚙️ تنظیمات (فقط نمایش)', callback_data=SETTINGS)],
        [InlineKeyboardButton('❓ راهنما', callback_data=HELP),
         InlineKeyboardButton('👤 درباره سازنده', callback_data=ABOUT)],
    ]
    return InlineKeyboardMarkup(rows)


def help_text() -> str:
    return ('<b>❓ راهنما</b>\n'
            'GatherRadar رویدادهای منابع منتخب را جمع‌آوری می‌کند و نتیجه را برای بررسی آماده می‌کند.\n\n'
            '<b>روند کار</b>\n'
            '۱. «🔄 کرال همه منابع» یا «🎯 انتخاب منابع» را بزنید.\n'
            '۲. خلاصه را ببینید و جمع‌آوری را تأیید کنید.\n'
            '۳. پیشرفت کار، زمان سپری‌شده و در صورت وجود داده کافی، زمان باقی‌مانده تقریبی را دنبال کنید.\n'
            '۴. فایل Excel را دریافت کنید یا رویدادها را به‌صورت متن مرور کنید.\n\n'
            '<b>مدیریت منابع:</b> افزودن منبع اینستاگرام یا وب‌سایت، فعال یا غیرفعال کردن، '
            'حذف از فهرست و بازیابی. حذف برگشت‌پذیر است و رویدادها و اجراهای قبلی پاک نمی‌شوند.\n'
            '<b>آخرین اجراها:</b> نتیجه، فایل Excel و رویدادهای هر اجرای قبلی.\n\n'
            'هر بار فقط یک جمع‌آوری انجام می‌شود و توقف پس از پایان منبع فعلی اعمال می‌شود.\n'
            '/menu منوی اصلی · /sources فهرست منابع · /cancel لغو گفتگوی جاری\n\n'
            'ساخته‌شده توسط Mohamad Mohebali')


def help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('👤 درباره سازنده', callback_data=ABOUT)],
        [InlineKeyboardButton('↩️ بازگشت به منوی اصلی', callback_data=MAIN)],
    ])


def about_text() -> str:
    return ('<b>درباره سازنده</b>\n'
            'GatherRadar ابزاری برای کشف، جمع‌آوری و بررسی رویدادها، دورهمی‌ها و تجربه‌های جدید است.\n\n'
            'طراحی و توسعه: Mohamad Mohebali')


def about_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('GitHub', url=CREATOR_GITHUB),
         InlineKeyboardButton('Repository', url=REPOSITORY)],
        [InlineKeyboardButton('↩️ بازگشت به منوی اصلی', callback_data=MAIN)],
    ])


def settings_text(limit: int, days: int) -> str:
    return '\n'.join([
        '<b>⚙️ تنظیمات</b> · فقط نمایش',
        f'از هر منبع: حداکثر {persian(limit)} مطلب اخیر',
        f'بازه رویدادها: {persian(days)} روز آینده',
        'منطقه زمانی نمایش: تهران',
        'تصاویر و ریل‌های اینستاگرام: بررسی می‌شوند (OCR محلی)',
        '',
        'تغییر این مقادیر از داخل ربات هنوز ممکن نیست؛ برای اجرای متفاوت از خط فرمان '
        '<code>gatherradar refresh</code> استفاده کنید.',
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)]])


# -- source list ----------------------------------------------------------------
def _state(view: SourceView) -> str:
    if view.archived:
        return '🗂 حذف‌شده از فهرست'
    if view.enabled:
        return '🟢 فعال'
    if view.disabled_reason in ('robots', 'terms'):
        return '⛔️ مسدود به‌دلیل سیاست سایت'
    if view.disabled_reason == 'unsupported':
        return '🟡 در انتظار پشتیبانی'
    return '⏸ غیرفعال'


def _icon(view: SourceView) -> str:
    return _state(view).split(' ', 1)[0]


def sources_text(views: tuple[SourceView, ...]) -> str:
    lines = ['<b>منابع ثبت‌شده</b>', f'فعال: {sum(v.enabled for v in views)} از {len(views)}']
    for kind in ('instagram', 'website'):
        group = [v for v in views if v.kind == kind]
        if not group:
            continue
        lines += ['', f'<b>{KINDS[kind]}</b>']
        lines += [f'{e(v.name)} — {_state(v)}' for v in group]
    lines += ['', 'برای جزئیات یک منبع را انتخاب کنید. تغییرات از «📋 مدیریت منابع» انجام می‌شود.']
    return '\n'.join(lines)


def _pages(count: int, size: int) -> int:
    return max(1, -(-count // size))


def _nav(prefix: str, page: int, pages: int, suffix: str = '') -> list[InlineKeyboardButton]:
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton('◀️ قبلی', callback_data=f'{prefix}{page - 1}{suffix}'))
    if page < pages - 1:
        nav.append(InlineKeyboardButton('بعدی ▶️', callback_data=f'{prefix}{page + 1}{suffix}'))
    return nav


def sources_keyboard(views: tuple[SourceView, ...], page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{_icon(v)} {clip(v.name, 40)}', callback_data=SOURCE + v.id)]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    if nav := _nav(SOURCES, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def source_text(view: SourceView) -> str:
    lines = [f'<b>{e(view.name)}</b>',
             f'نوع: {KINDS.get(view.kind, e(view.kind))}',
             f'وضعیت: {_state(view)}',
             f'شناسه: <code>{e(view.id)}</code>',
             f'نشانی: {e(clip(view.public_url, 200))}',
             f'منشأ: {"افزوده‌شده توسط شما" if view.origin == "local" else "فهرست اصلی پروژه"}']
    if not view.enabled and view.disabled_reason in REASONS:
        lines.append(f'دلیل غیرفعال بودن: {REASONS[view.disabled_reason]}')
    if view.locked:
        lines.append('این منبع تا رفع محدودیت یا افزودن پشتیبانی، از ربات قابل فعال‌سازی نیست.')
    return '\n'.join(lines)


def source_keyboard(view: SourceView | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📋 مدیریت این منبع', callback_data=MANAGE_VIEW + view.id if view else MANAGE)],
        [InlineKeyboardButton('↩️ فهرست منابع', callback_data=SOURCES + '0'),
         InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)],
    ])


def whoami_text(user_id: int, bootstrap: bool) -> str:
    text = f'شناسه عددی تلگرام شما: <code>{int(user_id)}</code>'
    if bootstrap:
        text += ('\n\nاین عدد را روی رایانه خودتان در متغیر GATHERRADAR_TELEGRAM_OWNER_ID '
                 'قرار دهید و ربات را دوباره اجرا کنید.')
    return text


# -- crawl configuration and source selection ----------------------------------
def crawl_confirm_text(views: tuple[SourceView, ...], all_enabled: bool, limit: int, days: int,
                       estimate=None) -> str:
    names = '، '.join(e(v.name) for v in views)
    count = persian(len(views))
    opening = (f'همه منابع فعال ({count} منبع) انتخاب شده‌اند.' if all_enabled
               else f'{count} منبع انتخاب شده‌اند.')
    lines = ['<b>تأیید جمع‌آوری</b>',
             f'{opening} از هر منبع حداکثر {persian(limit)} مورد اخیر بررسی می‌شود. '
             f'رویدادهای مرتبط با بازه {persian(days)} روز آینده برای مرور آماده خواهند شد.',
             '',
             f'منابع: {names}']
    if estimate is not None:
        lines.append(f'⌛ زمان تقریبی بر اساس اجراهای قبلی: {eta_range(estimate.low, estimate.high)}')
    else:
        lines.append('⌛ برای این منابع هنوز داده کافی برای تخمین زمان نداریم؛ زمان سپری‌شده نمایش داده می‌شود.')
    if any(v.kind == 'instagram' for v in views):
        lines.append('منابع اینستاگرام به‌دلیل بررسی تصاویر و متن داخل آن‌ها (OCR) معمولاً بیشتر طول می‌کشند '
                     'و مرورگر Chrome روی رایانه باز می‌شود.')
    lines += ['', 'آیا می‌خواهید جمع‌آوری شروع شود؟']
    return fit('\n'.join(lines))


def confirm_keyboard(nonce: str, back: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✅ شروع جمع‌آوری', callback_data=GO + nonce),
         InlineKeyboardButton('✖️ انصراف', callback_data=NO + nonce)],
        [InlineKeyboardButton('↩️ بازگشت', callback_data=back)],
    ])


def selection_text(views: tuple[SourceView, ...], selected: set[str]) -> str:
    chosen = [v for v in views if v.id in selected]
    lines = ['<b>انتخاب منابع</b>', 'منابع موردنظر را علامت بزنید و سپس «تأیید انتخاب» را بزنید.',
             f'انتخاب‌شده: {persian(len(chosen))} از {persian(len(views))}']
    if chosen:
        lines.append('، '.join(e(v.name) for v in chosen))
    return fit('\n'.join(lines))


def selection_keyboard(views: tuple[SourceView, ...], selected: set[str], page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{"☑️" if v.id in selected else "⬜️"} {v.name} · {KINDS[v.kind]}',
                                  callback_data=f'{SELECT}t:{v.id}:{page}')]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    if nav := _nav(SELECT, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('همه فعال‌ها', callback_data=f'{SELECT}all:{page}'),
                 InlineKeyboardButton('پاک کردن انتخاب', callback_data=f'{SELECT}clr:{page}')])
    rows.append([InlineKeyboardButton('✅ تأیید انتخاب', callback_data=SELECT + 'ok'),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


# -- job progress and completion -----------------------------------------------
NEXT_STEP = {
    'queued': 'در حال آماده‌سازی اجرا...',
    'starting': 'در حال آماده‌سازی اجرا...',
    'instagram': 'در حال دریافت پست‌ها و بررسی تصاویر رویدادها (OCR)؛ منابع اینستاگرام معمولاً بیشتر طول می‌کشند.',
    'website': 'در حال دریافت صفحه‌های رویداد از وب‌سایت...',
    'collecting': 'در حال رفتن به منبع بعدی...',
    'source': 'در حال بررسی منبع فعلی...',
    'analyzing': 'در حال استخراج و ادغام رویدادها؛ پس از آن نتایج ذخیره و فایل Excel ساخته می‌شود.',
    'persisting': 'در حال ذخیره نتایج در پایگاه داده محلی...',
    'exporting': 'در حال ساخت فایل Excel و خروجی‌ها...',
}


def job_text(job, names: dict[str, str], view=None, frame: int = 0) -> str:
    """Live status. `view` (ProgressView) carries monotonic elapsed time and an
    evidence-based estimate; without it only persisted facts are shown."""
    active = job.status in ('running', 'cancelling')
    title = '🔄 در حال جمع‌آوری رویدادها' if job.status == 'running' else (
        '⏹ در حال توقف' if job.status == 'cancelling' else f'اجرای کرال · {JOB_STATUS.get(job.status, e(job.status))}')
    if active:
        title += f' {SPINNER[frame % len(SPINNER)]}'
    lines = [f'<b>{title}</b>', f'مرحله: {STAGES.get(job.stage, e(job.stage))}']
    if job.total_sources:
        lines.append(f'منابع تکمیل‌شده: {persian(job.done_sources)} از {persian(job.total_sources)}')
    if job.current_source:
        current = e(names.get(job.current_source, job.current_source))
        if view is not None and view.current_kind in KINDS:
            current += f' ({KINDS[view.current_kind]})'
        lines.append(f'منبع فعلی: {current}')
    if view is not None and active:
        lines.append(f'⏱ زمان سپری‌شده: {duration(view.elapsed)}')
        if view.source_elapsed is not None and job.current_source:
            lines.append(f'زمان صرف‌شده برای منبع فعلی: {duration(view.source_elapsed)}')
        estimate = view.estimate
        if estimate is None:
            lines.append(NO_ESTIMATE)
        elif estimate.current_overrun:
            lines.append('⌛ این مرحله بیشتر از معمول طول کشیده است؛ اجرا همچنان فعال است و '
                         'تخمین قابل اتکایی برای باقی‌مانده نداریم.')
        else:
            lines.append(f'⌛ زمان باقی‌مانده تقریبی: {eta_range(estimate.low, estimate.high)}')
    if active:
        if job.current_source:
            key = view.current_kind if view is not None and view.current_kind in KINDS else 'source'
        else:
            key = job.stage
        if job.status == 'cancelling':
            lines.append('درخواست توقف ثبت شد؛ پس از پایان منبع فعلی اجرا متوقف می‌شود و نتیجه‌ای ثبت نمی‌شود.')
        elif key in NEXT_STEP:
            lines.append(NEXT_STEP[key])
    for source_id, status in job.source_status.items():
        lines.append(f'{SOURCE_STATUS.get(status, "•")} {e(names.get(source_id, source_id))}')
    if job.status == 'running' and job.stage in ('queued', 'starting', 'collecting'):
        lines += ['', 'با «⏹ توقف پس از منبع فعلی»، بررسی منبعِ در حال اجرا کامل می‌شود و سپس اجرا '
                      'بدون ثبت نتیجه متوقف می‌شود.']
    if job.message:
        lines += ['', e(job.message)]
    return fit('\n'.join(lines))


def job_keyboard(job) -> InlineKeyboardMarkup:
    rows = []
    if job.status == 'running' and job.stage in ('queued', 'starting', 'collecting'):
        rows.append([InlineKeyboardButton('⏹ توقف پس از منبع فعلی', callback_data=JOB_CANCEL)])
    rows.append([InlineKeyboardButton('🔄 به‌روزرسانی وضعیت', callback_data=JOB),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def run_summary_text(run, names: dict[str, str], export_ok: bool | None, title: str = 'نتیجه اجرا',
                     duration_seconds: float | None = None) -> str:
    statuses = {'success': [], 'partial': [], 'failed': []}
    for source_id in run.source_ids:
        statuses.setdefault(run.source_status.get(source_id, 'failed'), []).append(names.get(source_id, source_id))
    lines = [f'<b>{title}</b> · {JOB_STATUS.get(run.status, e(run.status))}',
             f'زمان: {when(run.started_at)} · {MODES.get(run.mode, e(run.mode))}']
    if duration_seconds:
        lines.append(f'⏱ مدت کل اجرا: {duration(duration_seconds)}')
    lines.append(f'منابع: {persian(len(run.source_ids))}')
    for key, label in (('success', '✅ تکمیل‌شده'), ('partial', '⚠️ با هشدار'), ('failed', '❌ ناموفق')):
        if statuses.get(key):
            lines.append(f'{label} ({persian(len(statuses[key]))}): ' + '، '.join(e(n) for n in statuses[key]))
    if statuses.get('partial'):
        lines.append('«با هشدار» یعنی بخشی از مطالب یا تصاویر آن منبع دریافت نشد؛ بقیه بررسی شد.')
    if run.persisted:
        lines += ['',
                  f'📌 رویدادهای یکتای پیش‌رو / در جریان: {persian(run.actionable or 0)}',
                  f'🗓 نیازمند بررسی زمان‌بندی: {persian(run.schedule_review or 0)}',
                  f'نامزدهای رویداد کشف‌شده: {persian(run.discovered or 0)} · '
                  f'بدون عنوان قابل‌اتکا (کنار گذاشته شد): {persian(run.excluded_missing_title or 0)}',
                  f'رویدادهای یکتا پس از ادغام تکراری‌ها: {persian(run.canonical or 0)} · '
                  f'گذشته: {persian(run.expired or 0)}']
        if not run.actionable and not run.schedule_review:
            lines.append('در این اجرا رویداد پیش‌رویی پیدا نشد. این خطا نیست؛ ممکن است منابع در این بازه '
                         'رویداد تازه‌ای اعلام نکرده باشند.')
    else:
        lines += ['', 'این اجرا به ثبت نتیجه نرسید و چیزی در پایگاه داده یا Excel تغییر نکرد.']
    if export_ok is True:
        lines.append('📥 خروجی Excel: آماده دریافت')
    elif export_ok is False:
        lines.append('خروجی Excel: ساخته نشد (داده‌ها در پایگاه داده ذخیره شده‌اند؛ اجرای بعدی آن را دوباره می‌سازد)')
    return fit('\n'.join(lines))


def outputs_keyboard(token: str | None, excel: bool, details: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if token and excel:
        rows.append([InlineKeyboardButton('📥 دریافت Excel', callback_data=EXCEL + token)])
    if token:
        rows.append([InlineKeyboardButton('📋 مشاهده رویدادها', callback_data=f'{EVENTS}{token}:a:0'),
                     InlineKeyboardButton('🗓 بررسی زمان‌بندی', callback_data=f'{EVENTS}{token}:r:0')])
    if token and details:
        rows.append([InlineKeyboardButton('🕘 جزئیات اجرا', callback_data=RUN + token)])
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def excel_caption(run, sheet: str, names: dict[str, str]) -> str:
    scope = '، '.join(names.get(i, i) for i in run.source_ids)
    return clip(f'GatherRadar · {when(run.started_at)}\nدامنه: {scope}\n'
                f'رویدادهای پیش‌رو: {persian(run.actionable or 0)} · بررسی زمان‌بندی: '
                f'{persian(run.schedule_review or 0)}\nبرگه این اجرا: {sheet}', 1000)


# -- run history ---------------------------------------------------------------
def runs_text(runs: tuple, page: int) -> str:
    if not runs:
        return '<b>آخرین اجراها</b>\nهنوز اجرایی ثبت نشده است.'
    return '<b>آخرین اجراها</b>\nبرای جزئیات و خروجی، یک اجرا را انتخاب کنید.'


def runs_keyboard(runs: tuple, page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(runs), RUNS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    rows = []
    for run in runs[page * RUNS_PER_PAGE:(page + 1) * RUNS_PER_PAGE]:
        label = (f'{when(run.started_at)} · {JOB_STATUS.get(run.status, run.status)} · '
                 f'{MODES.get(run.mode, run.mode)}')
        if run.persisted:
            label += f' · {persian(run.actionable or 0)} رویداد'
        rows.append([InlineKeyboardButton(label, callback_data=RUN + run.token)])
    if nav := _nav(RUNS, page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


# -- event browsing ------------------------------------------------------------
def _occurrence(record: dict) -> tuple[str, str]:
    """(date text, time text) from persisted values only; nothing is inferred."""
    if record.get('next_session_date'):
        return jalali(record['next_session_date']), clock(record.get('next_session_start_time'))
    if record.get('start_date') and record.get('end_date') and record['end_date'] != record['start_date']:
        return f'{jalali(record["start_date"])} تا {jalali(record["end_date"])}', clock(record.get('start_time'))
    if record.get('start_date'):
        return jalali(record['start_date']), clock(record.get('start_time'))
    occurrences = record.get('occurrences') or []
    if occurrences:
        first = min(occurrences, key=lambda o: (o.get('start_date') or '', o.get('start_time') or ''))
        return jalali(first.get('start_date')), clock(first.get('start_time'))
    return '', ''


def _place(record: dict) -> str:
    parts = [record.get('venue_name'), record.get('area_text'), record.get('city')]
    return '، '.join(e(p) for p in dict.fromkeys(p for p in parts if p))


def _first_line(text: str | None, limit: int) -> str:
    line = next((l.strip() for l in (text or '').splitlines() if l.strip()), '')
    return e(clip(line, limit)) if line else ''


def events_text(records: list[dict], kind: str, page: int, run) -> str:
    title = 'رویدادهای پیش‌رو و در جریان' if kind == 'a' else 'نیازمند بررسی زمان‌بندی'
    pages = _pages(len(records), EVENTS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    lines = [f'<b>{title}</b> · اجرای {when(run.started_at)}',
             f'تعداد: {persian(len(records))} · صفحه {persian(page + 1)} از {persian(pages)}']
    if not records:
        lines += ['', 'در این اجرا موردی در این بخش نیست.']
        return '\n'.join(lines)
    last_day = None
    for number, record in enumerate(records[page * EVENTS_PER_PAGE:(page + 1) * EVENTS_PER_PAGE],
                                    page * EVENTS_PER_PAGE + 1):
        day, hour = _occurrence(record)
        if kind == 'a' and day != last_day:
            lines += ['', f'— {day or "تاریخ نامشخص"} —']
            last_day = day
        elif kind == 'r':
            lines.append('')
        lines.append(f'<b>{persian(number)}. {e(clip(record.get("title") or "بدون عنوان", 90))}</b>')
        detail = []
        if kind == 'a':
            if hour:
                detail.append(f'🕒 {hour}')
        else:
            detail.append('🗓 ' + (e(clip(record.get('source_date_text') or '', 80)) or 'تاریخ اعلام نشده'))
        if place := _place(record):
            detail.append(f'📍 {place}')
        if detail:
            lines.append(' · '.join(detail))
        if summary := _first_line(record.get('description_text'), 110):
            lines.append(summary)
    return fit('\n'.join(lines))


def events_keyboard(records: list[dict], kind: str, page: int, token: str) -> InlineKeyboardMarkup:
    pages = _pages(len(records), EVENTS_PER_PAGE)
    page = min(max(page, 0), pages - 1)
    start = page * EVENTS_PER_PAGE
    numbers = [InlineKeyboardButton(f'مشاهده جزئیات {persian(i + 1)}', callback_data=f'{EVENT}{token}:{kind}:{i}')
               for i in range(start, min(start + EVENTS_PER_PAGE, len(records)))]
    rows = [numbers[i:i + 2] for i in range(0, len(numbers), 2)]
    if nav := _nav(f'{EVENTS}{token}:{kind}:', page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ خروجی‌ها', callback_data=RUN + token),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def event_text(record: dict, kind: str, index: int, total: int) -> str:
    day, hour = _occurrence(record)
    lines = [f'<b>{e(record.get("title") or "بدون عنوان")}</b>',
             f'مورد {persian(index + 1)} از {persian(total)}']
    category = CATEGORIES.get(record.get('category') or '') or record.get('source_category_text')
    if category:
        lines.append(f'نوع: {e(category)}')
    if kind == 'a':
        if record.get('next_session_date'):
            lines.append(f'جلسه بعدی: {day}' + (f'، ساعت {hour}' if hour else ''))
            if record.get('remaining_session_count'):
                lines.append(f'جلسه‌های باقی‌مانده در افق: {persian(record["remaining_session_count"])}')
        elif day:
            lines.append(f'تاریخ: {day}' + (f'، ساعت {hour}' if hour else ''))
    if record.get('source_date_text'):
        lines.append(f'زمان اعلام‌شده در منبع: {e(clip(record["source_date_text"], 200))}')
    if place := _place(record):
        lines.append(f'مکان: {place}')
    if record.get('address'):
        lines.append(f'آدرس: {e(clip(record["address"], 200))}')
    if record.get('price_text'):
        lines.append(f'هزینه: {e(clip(record["price_text"], 120))}')
    if record.get('availability_text'):
        lines.append(f'ظرفیت: {e(clip(record["availability_text"], 120))}')
    if record.get('readiness_explanation') and record.get('data_readiness') != 'ready_for_review':
        lines.append(f'نکته بررسی: {e(clip(record["readiness_explanation"], 300))}')
    if description := record.get('description_text'):
        lines += ['', e(clip(description, 900))]
    return fit('\n'.join(lines))


def event_keyboard(record: dict, kind: str, index: int, total: int, token: str) -> InlineKeyboardMarkup:
    rows = []
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton('◀️ قبلی', callback_data=f'{EVENT}{token}:{kind}:{index - 1}'))
    if index < total - 1:
        nav.append(InlineKeyboardButton('بعدی ▶️', callback_data=f'{EVENT}{token}:{kind}:{index + 1}'))
    if nav:
        rows.append(nav)
    url = record.get('canonical_source_url') or ''
    if url.startswith(('https://', 'http://')):
        rows.append([InlineKeyboardButton('🔗 مشاهده منبع', url=url)])
    page = index // EVENTS_PER_PAGE
    rows.append([InlineKeyboardButton('✖️ بستن جزئیات', callback_data=f'{EVENTS}{token}:{kind}:{page}'),
                 InlineKeyboardButton('↩️ بازگشت به فهرست', callback_data=f'{EVENTS}{token}:{kind}:0')])
    return InlineKeyboardMarkup(rows)


# -- source management (Phase 3) -------------------------------------------------
LIST_TITLES = {'l': '📚 منابع', 'a': '⏸ غیرفعال‌سازی منبع', 'd': '▶️ فعال‌سازی منبع',
               'x': '♻️ بازیابی منابع حذف‌شده'}
LIST_HINTS = {'l': 'برای دیدن جزئیات و تغییر وضعیت، یک منبع را انتخاب کنید.',
              'a': 'منبع فعالی را که می‌خواهید موقتاً از کرال‌ها خارج شود انتخاب کنید.',
              'd': 'منبع غیرفعالی را که می‌خواهید دوباره در کرال‌ها شرکت کند انتخاب کنید.',
              'x': 'منابع حذف‌شده از فهرست؛ برای بازگرداندن یکی را انتخاب کنید.'}
LIST_EMPTY = {'l': 'هنوز منبعی ثبت نشده است.', 'a': 'منبع فعالی وجود ندارد.',
              'd': 'منبع غیرفعالی وجود ندارد.', 'x': 'منبع حذف‌شده‌ای وجود ندارد.'}
ACTIONS = {'e': 'enable', 'd': 'disable', 'x': 'archive', 'r': 'restore'}
ACTION_DONE = {'enable': 'منبع فعال شد و در کرال‌های بعدی شرکت می‌کند.',
               'disable': 'منبع غیرفعال شد و در کرال‌های بعدی شرکت نمی‌کند. اطلاعات قبلی آن حفظ شده است.',
               'archive': 'منبع از فهرست حذف شد. اطلاعات و اجراهای قبلی حفظ شده‌اند و می‌توانید آن را بازیابی کنید.',
               'restore': 'منبع به فهرست برگشت و فعلاً غیرفعال است؛ برای شرکت در کرال آن را فعال کنید.'}
ERRORS = {
    'empty': 'چیزی دریافت نشد. نشانی را به‌صورت متن بفرستید.',
    'format': 'قالب ورودی معتبر نیست. نشانی را بدون فاصله و به‌صورت کامل بفرستید.',
    'ig_url': 'این نشانی صفحه اینستاگرام نیست. نمونه درست: @example_account یا https://www.instagram.com/example_account/',
    'ig_not_profile': 'این نشانی یک پست، ریل یا بخش دیگری از اینستاگرام است، نه صفحه پروفایل.',
    'ig_username': 'نام کاربری معتبر نیست: فقط حروف انگلیسی، عدد، نقطه و زیرخط، حداکثر ۳۰ نویسه.',
    'credentials': 'نشانی نباید نام کاربری، رمز عبور یا درگاه (port) داشته باشد.',
    'scheme': 'فقط نشانی‌های http یا https پذیرفته می‌شوند.',
    'port': 'نشانی با درگاه (port) غیرمعمول پذیرفته نمی‌شود.',
    'private': 'این نشانی به رایانه محلی یا شبکه خصوصی اشاره می‌کند و پذیرفته نمی‌شود.',
    'dns': 'این دامنه پیدا نشد. نشانی را بررسی کنید و دوباره بفرستید.',
    'is_instagram': 'این نشانی اینستاگرام است؛ برای آن گزینه «اینستاگرام» را انتخاب کنید.',
    'duplicate': 'این منبع قبلاً ثبت شده است',
    'duplicate_id': 'این منبع قبلاً ثبت شده است',
    'duplicate_source': 'این منبع قبلاً ثبت شده است',
    'registry_busy': 'فهرست منابع در حال تغییر است؛ چند لحظه بعد دوباره تلاش کنید.',
    'locked': 'این منبع به‌دلیل سیاست سایت یا نبود پشتیبانی، از ربات قابل فعال‌سازی نیست.',
    'archived': 'این منبع حذف‌شده است؛ ابتدا آن را بازیابی کنید.',
    'robots_disallowed': 'robots.txt این سایت اکنون اجازه جمع‌آوری نمی‌دهد؛ منبع فعال نشد.',
    'too_many_sources': 'تعداد منابع افزوده‌شده به سقف مجاز رسیده است.',
    'overlay_disabled': 'ذخیره منابع محلی در این نصب غیرفعال است.',
    'busy': 'یک کرال در جریان است. منابع آن اجرا هنگام تأیید ثبت شده‌اند؛ تغییر منابع پس از پایان آن ممکن است.',
    'expired': 'این گفتگو منقضی شده یا ربات دوباره راه‌اندازی شده است. چیزی ذخیره نشد؛ از «📋 مدیریت منابع» دوباره شروع کنید.',
    'stale': 'وضعیت این منبع تغییر کرده است. فهرست را دوباره باز کنید.',
}


def error_text(code: str, source_id: str | None = None, archived: bool = False) -> str:
    text = ERRORS.get(code, 'این درخواست انجام نشد. دوباره تلاش کنید.')
    if code.startswith('duplicate'):
        text += f' (شناسه: <code>{e(source_id or "")}</code>).'
        if archived:
            text += ' این منبع حذف‌شده است؛ می‌توانید آن را از «♻️ بازیابی منابع حذف‌شده» برگردانید.'
        else:
            text += ' برای تغییر وضعیت، آن را از فهرست منابع باز کنید.'
    return text


def manage_text(counts: dict[str, int], notice: str | None = None) -> str:
    lines = ['<b>📋 مدیریت منابع</b>',
             'منابعی که GatherRadar بررسی می‌کند را از این بخش مدیریت کنید.',
             '',
             f'🟢 فعال: {persian(counts["active"])} · ⏸ غیرفعال: {persian(counts["disabled"])} · '
             f'🗂 حذف‌شده: {persian(counts["archived"])}',
             f'اینستاگرام: {persian(counts["instagram"])} · وب‌سایت: {persian(counts["website"])}']
    if notice:
        lines += ['', notice]
    return '\n'.join(lines)


def manage_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('➕ افزودن منبع', callback_data=ADD),
         InlineKeyboardButton('📚 مشاهده منابع', callback_data=MANAGE_LIST + 'l:0')],
        [InlineKeyboardButton('⏸ غیرفعال‌سازی منبع', callback_data=MANAGE_LIST + 'a:0'),
         InlineKeyboardButton('▶️ فعال‌سازی منبع', callback_data=MANAGE_LIST + 'd:0')],
        [InlineKeyboardButton('🗂 حذف از فهرست', callback_data=MANAGE_LIST + 'l:0'),
         InlineKeyboardButton('♻️ بازیابی منابع حذف‌شده', callback_data=MANAGE_LIST + 'x:0')],
        [InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)],
    ])


def filter_views(views: tuple[SourceView, ...], kind: str) -> tuple[SourceView, ...]:
    if kind == 'x':
        return tuple(v for v in views if v.archived)
    listed = tuple(v for v in views if not v.archived)
    if kind == 'a':
        return tuple(v for v in listed if v.enabled)
    if kind == 'd':
        return tuple(v for v in listed if not v.enabled)
    return listed


def manage_list_text(views: tuple[SourceView, ...], kind: str, page: int) -> str:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    lines = [f'<b>{LIST_TITLES[kind]}</b>']
    if not views:
        lines.append(LIST_EMPTY[kind])
        return '\n'.join(lines)
    lines += [LIST_HINTS[kind], f'تعداد: {persian(len(views))} · صفحه {persian(page + 1)} از {persian(pages)}', '']
    for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]:
        lines.append(f'{_icon(v)} {e(clip(v.name, 50))} · {KINDS[v.kind]} · <code>{e(v.id)}</code>')
    return fit('\n'.join(lines))


def manage_list_keyboard(views: tuple[SourceView, ...], kind: str, page: int) -> InlineKeyboardMarkup:
    pages = _pages(len(views), PAGE_SIZE)
    page = min(max(page, 0), pages - 1)
    rows = [[InlineKeyboardButton(f'{_icon(v)} {clip(v.name, 34)} · {KINDS[v.kind]}', callback_data=MANAGE_VIEW + v.id)]
            for v in views[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]]
    if nav := _nav(f'{MANAGE_LIST}{kind}:', page, pages):
        rows.append(nav)
    rows.append([InlineKeyboardButton('↩️ مدیریت منابع', callback_data=MANAGE),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def manage_source_keyboard(view: SourceView) -> InlineKeyboardMarkup:
    rows = []
    if view.archived:
        rows.append([InlineKeyboardButton('♻️ بازیابی به فهرست', callback_data=f'{MANAGE_ACT}r:{view.id}')])
    else:
        if view.enabled:
            rows.append([InlineKeyboardButton('⏸ غیرفعال‌سازی', callback_data=f'{MANAGE_ACT}d:{view.id}')])
        elif not view.locked:
            rows.append([InlineKeyboardButton('▶️ فعال‌سازی', callback_data=f'{MANAGE_ACT}e:{view.id}')])
        rows.append([InlineKeyboardButton('🗂 حذف از فهرست', callback_data=f'{MANAGE_ACT}x:{view.id}')])
    rows.append([InlineKeyboardButton('↩️ بازگشت', callback_data=MANAGE_LIST + ('x:0' if view.archived else 'l:0')),
                 InlineKeyboardButton('↩️ منوی اصلی', callback_data=MAIN)])
    return InlineKeyboardMarkup(rows)


def action_confirm_text(view: SourceView, action: str) -> str:
    name = f'<b>{e(view.name)}</b> (<code>{e(view.id)}</code>)'
    if action == 'archive':
        return '\n'.join(['<b>🗂 حذف منبع از فهرست</b>', name, '',
                          'این منبع دیگر در فهرست فعال نمایش داده نمی‌شود و در Crawlهای آینده شرکت نمی‌کند.',
                          'اطلاعات و اجراهای قبلی حفظ می‌شوند.', '', 'آیا مطمئن هستید؟'])
    if action == 'disable':
        return '\n'.join(['<b>⏸ غیرفعال‌سازی منبع</b>', name, '',
                          'این منبع در Crawlهای بعدی و فهرست انتخاب منابع شرکت نمی‌کند. رویدادها، شواهد، '
                          'اجراهای قبلی و تصمیم‌های بررسی شما حفظ می‌شوند و می‌توانید آن را دوباره فعال کنید.',
                          '', 'ادامه می‌دهید؟'])
    if action == 'enable':
        extra = ('برای وب‌سایت‌ها پیش از فعال‌سازی دوباره robots.txt بررسی می‌شود. ' if view.kind == 'website' else
                 'دسترسی به حساب‌های اینستاگرام در اولین کرال بررسی می‌شود؛ حساب خصوصی یا محدود به‌صورت خطای همان منبع گزارش می‌شود. ')
        return '\n'.join(['<b>▶️ فعال‌سازی منبع</b>', name, '',
                          'این منبع در Crawlهای بعدی شرکت می‌کند. ' + extra + 'هیچ کرالی خودکار شروع نمی‌شود.',
                          '', 'ادامه می‌دهید؟'])
    return '\n'.join(['<b>♻️ بازیابی منبع</b>', name, '',
                      'منبع به فهرست برمی‌گردد اما غیرفعال می‌ماند تا خودتان آن را فعال کنید.', '', 'ادامه می‌دهید؟'])


def action_confirm_keyboard(nonce: str, action: str, source_id: str) -> InlineKeyboardMarkup:
    label = {'archive': 'تأیید حذف', 'disable': 'تأیید غیرفعال‌سازی', 'enable': 'تأیید فعال‌سازی',
             'restore': 'تأیید بازیابی'}[action]
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(label, callback_data=MANAGE_OK + nonce),
         InlineKeyboardButton('انصراف', callback_data=MANAGE_NO + nonce)],
        [InlineKeyboardButton('↩️ بازگشت', callback_data=MANAGE_VIEW + source_id)],
    ])


# -- guided add-source conversation ---------------------------------------------------
def add_type_text() -> str:
    return ('<b>➕ افزودن منبع</b> · مرحله ۱ از ۳\n'
            'نوع منبع را انتخاب کنید.\n\n'
            'پس از ثبت، هیچ کرالی خودکار شروع نمی‌شود و رمز عبور هیچ حسابی پرسیده نمی‌شود.')


def add_type_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('📸 اینستاگرام', callback_data=ADD + ':i'),
         InlineKeyboardButton('🌐 وب‌سایت', callback_data=ADD + ':w')],
        [InlineKeyboardButton('✖️ انصراف', callback_data=ADD_CANCEL)],
    ])


def add_input_text(kind: str, error: str | None = None) -> str:
    if kind == 'instagram':
        lines = ['<b>➕ افزودن منبع اینستاگرام</b> · مرحله ۲ از ۳',
                 'نام کاربری یا نشانی صفحه را به‌صورت یک پیام بفرستید، مثلاً:',
                 '<code>@example_account</code>',
                 '<code>https://www.instagram.com/example_account/</code>']
    else:
        lines = ['<b>➕ افزودن منبع وب‌سایت</b> · مرحله ۲ از ۳',
                 'نشانی عمومی صفحه فهرست رویدادها را بفرستید، مثلاً:',
                 '<code>https://example.com/events</code>',
                 'فقط وب‌سایت‌هایی قابل اجرا هستند که ساختارشان از قبل پشتیبانی می‌شود؛ بقیه ثبت می‌شوند '
                 'اما تا افزودن پشتیبانی اجرا نمی‌شوند.']
    if error:
        lines += ['', f'⚠️ {error}', 'دوباره بفرستید یا انصراف دهید.']
    return '\n'.join(lines)


def add_input_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton('↩️ بازگشت', callback_data=ADD),
                                  InlineKeyboardButton('✖️ انصراف', callback_data=ADD_CANCEL)]])


PROPOSAL_STATUS = {'ready': 'آماده فعال‌سازی', 'needs_review': 'نیازمند بررسی',
                   'unsupported': 'در انتظار پشتیبانی (غیرقابل اجرا)',
                   'policy_blocked': 'مسدود به‌دلیل سیاست سایت (غیرقابل اجرا)'}


def preview_text(proposal) -> str:
    source = proposal.source
    kind = 'Instagram' if source.source_type.value == 'instagram' else 'Website'
    lines = ['<b>منبع جدید</b> · مرحله ۳ از ۳',
             f'نوع: {kind}',
             f'شناسه: <code>{e(source.id)}</code>',
             f'آدرس: {e(clip(source.url, 200))}',
             f'وضعیت: {PROPOSAL_STATUS[proposal.status]}', '']
    if kind == 'Instagram':
        lines.append('دسترسی به این حساب هنوز بررسی نشده است. کرال با همان پروفایل Chrome روی رایانه شما انجام '
                     'می‌شود؛ اگر حساب خصوصی یا محدود باشد، در اولین کرال به‌عنوان خطای همین منبع گزارش می‌شود.')
    elif proposal.status == 'unsupported':
        lines.append('این وب‌سایت ثبت می‌شود، اما ساختار آن هنوز توسط GatherRadar پشتیبانی نمی‌شود. '
                     'برای فعال‌سازی Crawl به بررسی یا Adapter اختصاصی نیاز دارد و تا آن زمان اجرا نمی‌شود.')
    elif proposal.status == 'policy_blocked':
        lines.append(f'{REASONS.get(proposal.reason, "سیاست سایت اجازه جمع‌آوری نمی‌دهد")}؛ '
                     'منبع غیرفعال ثبت می‌شود و هرگز اجرا نمی‌شود.')
    elif proposal.robots == 'allowed':
        lines.append('ساختار این نشانی با یک Adapter موجود پشتیبانی می‌شود و robots.txt اجازه بررسی می‌دهد.')
    else:
        lines.append('ساختار این نشانی پشتیبانی می‌شود، اما robots.txt الان قابل بررسی نبود. '
                     'پیش از هر کرال دوباره بررسی می‌شود و در صورت منع، چیزی دریافت نمی‌شود.')
    lines += ['', 'آیا این منبع اضافه شود؟']
    return '\n'.join(lines)


def preview_keyboard(nonce: str, runnable: bool) -> InlineKeyboardMarkup:
    if runnable:
        first = [InlineKeyboardButton('✅ افزودن و فعال‌سازی', callback_data=f'{SAVE}{nonce}:a'),
                 InlineKeyboardButton('💾 افزودن (غیرفعال)', callback_data=f'{SAVE}{nonce}:p')]
    else:
        first = [InlineKeyboardButton('💾 ثبت به‌صورت غیرفعال', callback_data=f'{SAVE}{nonce}:p')]
    return InlineKeyboardMarkup([first, [InlineKeyboardButton('↩️ ویرایش نشانی', callback_data=ADD_BACK),
                                         InlineKeyboardButton('✖️ انصراف', callback_data=ADD_CANCEL)]])


def saved_text(entry, activated: bool) -> str:
    source = entry.source
    if source.disabled_reason == 'unsupported':
        state = ('این وب‌سایت ثبت شد، اما ساختار آن هنوز توسط GatherRadar پشتیبانی نمی‌شود. '
                 'برای فعال‌سازی Crawl به بررسی یا Adapter اختصاصی نیاز دارد.')
    elif source.disabled_reason in ('robots', 'terms'):
        state = 'منبع به‌صورت غیرفعال ثبت شد و به‌دلیل سیاست سایت اجرا نمی‌شود.'
    elif activated:
        state = 'منبع فعال است و در کرال بعدی (همه منابع یا انتخاب منابع) شرکت می‌کند. هیچ کرالی خودکار شروع نشد.'
    else:
        state = 'منبع غیرفعال ثبت شد؛ هر زمان خواستید از «▶️ فعال‌سازی منبع» آن را فعال کنید.'
    return '\n'.join(['<b>✅ منبع ذخیره شد</b>', f'{e(source.name)} · <code>{e(source.id)}</code>', '', state])
