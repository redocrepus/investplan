"""ISO currency list and locale-based default currency detection."""

import locale

COMMON_CURRENCIES: list[str] = [
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "SEK", "NOK", "DKK", "SGD", "HKD", "KRW", "CNY", "INR",
    "BRL", "MXN", "ZAR", "TRY", "PLN", "CZK", "HUF", "ILS",
    "THB", "TWD", "RUB", "AED", "SAR",
]

# Mapping of locale prefixes to ISO currency codes
_LOCALE_CURRENCY_MAP: dict[str, str] = {
    "en_US": "USD", "en_GB": "GBP", "en_AU": "AUD", "en_CA": "CAD",
    "en_NZ": "NZD", "en_SG": "SGD", "en_HK": "HKD", "en_IN": "INR",
    "en_ZA": "ZAR", "de_DE": "EUR", "de_AT": "EUR", "fr_FR": "EUR",
    "fr_CA": "CAD", "fr_CH": "CHF", "it_IT": "EUR", "es_ES": "EUR",
    "es_MX": "MXN", "pt_BR": "BRL", "ja_JP": "JPY", "ko_KR": "KRW",
    "zh_CN": "CNY", "zh_TW": "TWD", "zh_HK": "HKD", "sv_SE": "SEK",
    "nb_NO": "NOK", "da_DK": "DKK", "pl_PL": "PLN", "cs_CZ": "CZK",
    "hu_HU": "HUF", "he_IL": "ILS", "th_TH": "THB", "tr_TR": "TRY",
    "ru_RU": "RUB", "ar_AE": "AED", "ar_SA": "SAR",
}


def get_locale_currency() -> str:
    """Return the ISO currency code for the current system locale, defaulting to USD."""
    try:
        loc = locale.getdefaultlocale()[0] or ""
    except ValueError:
        return "USD"
    # Try exact match first, then language_country prefix
    if loc in _LOCALE_CURRENCY_MAP:
        return _LOCALE_CURRENCY_MAP[loc]
    prefix = loc.split(".")[0]
    if prefix in _LOCALE_CURRENCY_MAP:
        return _LOCALE_CURRENCY_MAP[prefix]
    return "USD"
