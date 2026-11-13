import unittest
from decimal import Decimal, localcontext

from gatherradar.normalization import NormalizationStatus, normalize_price


class PriceNormalizationTests(unittest.TestCase):
    def test_persian_toman(self):
        self.assertEqual(normalize_price('۳۵۰ هزار تومان').price_amount, Decimal(350000))
        self.assertEqual(normalize_price('۳۵۰ هزار تومان').currency, 'TOMAN')

    def test_latin_toman(self):
        self.assertEqual(normalize_price('350 هزار تومان').price_amount, Decimal(350000))

    def test_arabic_digits(self):
        self.assertEqual(normalize_price('٣٥٠ هزار تومان').price_amount, Decimal(350000))

    def test_separators(self):
        for text in ('۱٬۲۰۰٬۰۰۰ تومان', '1,200,000 تومان'):
            self.assertEqual(normalize_price(text).price_amount, Decimal(1200000))

    def test_million(self):
        self.assertEqual(normalize_price('۲ میلیون تومن').price_amount, Decimal(2000000))

    def test_decimal_scale(self):
        self.assertEqual(normalize_price('۱٫۵ میلیون تومان').price_amount, Decimal(1500000))

    def test_rial_is_not_toman(self):
        result = normalize_price('۳۵۰۰۰۰ ریال')
        self.assertEqual((result.price_amount, result.currency), (Decimal(350000), 'IRR'))

    def test_script_variants(self):
        self.assertEqual(normalize_price('۲ ميليون ريال').price_amount, Decimal(2000000))

    def test_free(self):
        for text in ('رایگان', 'بدون هزینه', 'free', 'free admission', 'ورودی: رایگان'):
            result = normalize_price(text)
            self.assertEqual(result.price_amount, Decimal(0))
            self.assertIsNone(result.currency)

    def test_missing_not_free(self):
        for text in (None, '', '   '):
            result = normalize_price(text)
            self.assertIsNone(result.price_amount)
            self.assertEqual(result.status, NormalizationStatus.UNRESOLVED)

    def test_ranges(self):
        for text in ('از ۳۰۰ تا ۵۰۰ هزار تومان', '۳۰۰-۵۰۰ هزار تومان', 'از ۳۰۰ تومان', 'تا ۵۰۰ تومان'):
            self.assertIsNone(normalize_price(text).price_amount)

    def test_tiers_and_conditions(self):
        for text in ('اعضا ۳۰۰ تومان، دیگران ۵۰۰ تومان', '۳۰۰ تومان با تخفیف', 'رایگان برای کودکان',
                     'رایگان نیست', 'free with purchase', '۳۰۰ تومان یا ۴۰۰ تومان'):
            self.assertIsNone(normalize_price(text).price_amount)

    def test_explicit_currencies(self):
        for text, amount, currency in [('USD 12.50', '12.50', 'USD'), ('۲۵ یورو', '25', 'EUR'),
                                      ('GBP 10', '10', 'GBP'), ('€ 15', '15', 'EUR'), ('۱ دلار آمریکا', '1', 'USD')]:
            result = normalize_price(text)
            self.assertEqual((result.price_amount, result.currency), (Decimal(amount), currency))

    def test_ambiguous_dollar_not_usd(self):
        for text in ('$20', '۲۰ دلار', '20 dollars'):
            self.assertIsNone(normalize_price(text).price_amount)

    def test_labels(self):
        self.assertEqual(normalize_price('ورودی ۳۵۰ هزار تومان').price_amount, Decimal(350000))

    def test_malformed_numbers(self):
        for text in ('۱۲٬۳۴ تومان', '-۲۰ تومان', '1e3 USD', 'NaN USD', '12 000 تومان', '۱۲،۰۰۰ تومان'):
            self.assertIsNone(normalize_price(text).price_amount)

    def test_decimal_context_determinism(self):
        expected = normalize_price('۱۲۳۴۵۶٫۷۸ هزار تومان')
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(normalize_price('۱۲۳۴۵۶٫۷۸ هزار تومان'), expected)

    def test_bound_and_large_amount(self):
        self.assertIsNone(normalize_price('۹' * 4097).price_amount)
        self.assertIsNone(normalize_price('1234567890123456789 USD').price_amount)
