"""Shared Persian review schema; independent of spreadsheet clients."""
from __future__ import annotations


SCHEMA_VERSION = 1
GUIDE, RUNS, DUPLICATES, EVENT_MAP, SYNC_STATE = (
    'راهنما', 'اجراها', 'تکراری‌های احتمالی', '_event_map', '_sync_state',
)
DECISIONS = ('بررسی نشده', 'علاقه‌مندم', 'می‌خوام برم', 'رفتم', 'رد شد')
DUPLICATE_DECISIONS = ('بررسی نشده', 'یکی هستند', 'جدا هستند')
# Summary is not shown: it is reserved for a future summary contract. The
# source's own description is shown instead, never generated prose.
EVENT_VISIBLE = (
    'تصمیم من', 'عنوان', 'دسته‌بندی', 'وضعیت رویداد', 'تاریخ شمسی شروع', 'روز',
    'ساعت شروع', 'تاریخ شمسی پایان', 'ساعت پایان', 'زمان‌بندی اعلام‌شده', 'مکان',
    'منطقه / محله', 'شهر', 'آدرس', 'مدت', 'هزینه', 'ظرفیت / وضعیت ثبت‌نام', 'فرمت',
    'توضیحات / معرفی', 'برگزارکننده', 'ثبت‌نام / خرید', 'منبع اصلی', 'همه منابع',
    'تعداد منابع', 'کیفیت داده', 'یادداشت من',
    'آمادگی داده', 'دلیل بررسی', 'جلسه‌ها',
)
EVENT_TECHNICAL = (
    'event_id', 'run_id', 'start_date_iso', 'end_date_iso', 'timezone', 'date_precision',
    'starts_at_iso', 'ends_at_iso', 'price_amount', 'currency', 'source_date_text',
    'source_schedule_text',
    'source_ids', 'publisher_keys', 'candidate_ids', 'source_item_ids', 'evidence_urls',
    'canonical_source_url', 'diagnostics', 'first_seen_at', 'last_seen_at',
    'duplicate_group_id', 'field_provenance', 'extraction_confidence',
    'occurrences', 'schedule_kind', 'recurrence_rule', 'data_readiness',
    'readiness_reasons', 'quality_indicators',
    'source_title', 'display_title_origin', 'display_title_evidence_ids',
    'title_evidence_text', 'title_review_required', 'event_detection_reason',
)
EVENT_HEADERS = EVENT_VISIBLE + EVENT_TECHNICAL
PLACE_VISIBLE = ('تصمیم من', 'نام مکان', 'دسته‌بندی', 'شهر', 'آدرس', 'ساعات فعالیت',
                 'هزینه', 'خلاصه', 'منبع', 'یادداشت من')
PLACE_HEADERS = PLACE_VISIBLE + ('candidate_id', 'raw_item_id', 'source_id', 'run_id', 'evidence_url')
RUN_HEADERS = ('run_id', 'تاریخ اجرا', 'زمان اجرا', 'بازه آینده (روز)', 'وضعیت اجرا',
    'تعداد سورس‌ها', 'رویدادها', 'مکان‌ها', 'تکراری احتمالی', 'خطاهای سورس',
    'تب رویدادها', 'تب مکان‌ها', 'started_at_iso', 'finished_at_iso',
    'event_sheet_id', 'place_sheet_id', 'filtered_count', 'undated_count')
DUPLICATE_HEADERS = ('تصمیم', 'رویداد A', 'تاریخ A', 'منابع A', 'رویداد B', 'تاریخ B',
    'منابع B', 'دلیل پیشنهاد', 'یادداشت من', 'pair_key', 'event_id_a', 'event_id_b',
    'first_seen_run', 'last_seen_run', 'reason_codes')
MAP_HEADERS = ('event_id', 'anchor_raw_item_id', 'anchor_slot', 'first_seen_run', 'last_seen_run')
STATE_HEADERS = ('key', 'value')
GUIDE_ROWS = [
    ['GatherRadar', 'راهنمای مرور فرصت‌ها'],
    ['شروع', 'python -m gatherradar refresh --all-enabled --days 14'],
    ['بازخوانی داده محلی', 'python -m gatherradar sheets sync --all-enabled --days 14'],
    ['تاریخچه', 'هر اجرا یک تصویر مستقل است؛ اجراهای قبلی بازنویسی یا حذف نمی‌شوند.'],
    ['تصمیم من و یادداشت من', 'این ستون‌ها متعلق به شما هستند و با شناسه ثابت رویداد به اجرای بعد منتقل می‌شوند.'],
    ['تصمیم‌ها', 'بررسی نشده / علاقه‌مندم / می‌خوام برم / رفتم / رد شد'],
    ['ستون‌های پنهان', 'شناسه‌ها، تاریخ میلادی و مسیر شواهد برای بررسی فنی نگه داشته می‌شوند.'],
    ['شواهد', 'متن کامل منبع و OCR در رایانه می‌ماند؛ اصلاح دستی سلول، شاهد منبع نیست.'],
    ['کیفیت داده', 'تاریخ نامشخص، اطلاعات ناقص و تعارض‌ها نیازمند بررسی شما هستند.'],
    ['آمادگی داده', 'با فیلتر این ستون، آماده بررسی، نیاز به تکمیل، بررسی زمان‌بندی و منبع ناموجود را جدا کنید. این وضعیت تصمیم شما نیست.'],
    ['جلسه‌ها', 'تاریخ و ساعت هر جلسه فقط با شاهد منبع نمایش داده می‌شود؛ قیمت و ظرفیت هر جلسه مستقل است. تکرار هفتگی بدون تاریخ گسترش نمی‌یابد.'],
    ['مکان / منطقه / آدرس', 'مکان نام محل برگزاری است؛ منطقه / محله محدوده تقریبی اعلام‌شده است و آدرس دقیق نیست.'],
    ['زمان‌بندی اعلام‌شده', 'متن دقیق زمان‌بندی منبع؛ برای جلسات متعدد یا تاریخ ناقص. هیچ جلسه‌ای ساخته نمی‌شود.'],
    ['توضیحات / معرفی', 'متن توضیحات خود منبع، بدون خلاصه‌سازی یا هوش مصنوعی.'],
    ['ظرفیت / وضعیت ثبت‌نام', 'عبارت صریح منبع؛ فقط «تکمیل ظرفیت» و معادل‌های صریح وضعیت را تکمیل ظرفیت می‌کند. علامت تکمیل ظرفیت یا تعداد صندلی جلسه‌ها عین داده منبع است و تضمین رزرو نیست.'],
    ['سه وضعیت جدا', 'برگه «رویدادها» یعنی تاریخ رویداد امروز تا پایان بازه است (نه تأیید کامل جزئیات)؛ «آمادگی داده» کامل بودن و تعارض داده‌ها را نشان می‌دهد؛ «ظرفیت / وضعیت ثبت‌نام» و «وضعیت رویداد» امکان رزرو را طبق منبع نشان می‌دهند.'],
    ['تعارض منبع', 'وقتی منبع دو مقدار متفاوت گفته (مثلاً مدت «۲ ساعت» و «سه‌ساعته»)، هیچ‌کدام انتخاب نمی‌شود و هر دو در «دلیل بررسی» آمده‌اند.'],
    ['مکان‌ها', 'مکان‌ها جدا از رویدادها هستند؛ حذف تکرار مکان بین منابع پیاده‌سازی نشده است.'],
    ['تکراری‌ها', 'تصمیم و یادداشت حفظ می‌شوند؛ تصمیم دستی فعلاً نتیجه تطبیق خودکار را تغییر نمی‌دهد.'],
    ['بازه', 'رویدادهای هم‌پوشان با امروز تا پایان بازه و موارد بدون تاریخ نمایش داده می‌شوند.'],
]
PERMANENT = {
    GUIDE: (tuple(GUIDE_ROWS[0]), 2), RUNS: (RUN_HEADERS, 12),
    DUPLICATES: (DUPLICATE_HEADERS, 9), EVENT_MAP: (MAP_HEADERS, 0),
    SYNC_STATE: (STATE_HEADERS, 0),
}

