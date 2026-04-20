# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Translation methods for generating localized strings.

To load a locale and generate a translated string::

    user_locale = tornado.locale.get("es_LA")
    print(user_locale.translate("Sign out"))

`tornado.locale.get()` returns the closest matching locale, not necessarily the
specific locale you requested. You can support pluralization with
additional arguments to `~Locale.translate()`, e.g.::

    people = [...]
    message = user_locale.translate(
        "%(list)s is online", "%(list)s are online", len(people))
    print(message % {"list": user_locale.list(people)})

The first string is chosen if ``len(people) == 1``, otherwise the second
string is chosen.

Applications should call one of `load_translations` (which uses a simple
CSV format) or `load_gettext_translations` (which uses the ``.mo`` format
supported by `gettext` and related tools).  If neither method is called,
the `Locale.translate` method will simply return the original string.
"""

from __future__ import annotations

import codecs
import csv
import datetime
import gettext
import glob
import os
import re
from collections.abc import Iterable
from typing import Any

from tornado import escape
from tornado._locale_data import LOCALE_NAMES
from tornado.log import gen_log

_default_locale = "en_US"
_translations: dict[str, Any] = {}
_supported_locales = frozenset([_default_locale])
_use_gettext = False
CONTEXT_SEPARATOR = "\x04"


def get(*locale_codes: str) -> Locale:
    """Returns the closest match for the given locale codes.

    We iterate over all given locale codes in order. If we have a tight
    or a loose match for the code (e.g., "en" for "en_US"), we return
    the locale. Otherwise we move to the next code in the list.

    By default we return ``en_US`` if no translations are found for any of
    the specified locales. You can change the default locale with
    `set_default_locale()`.
    """
    return Locale.get_closest(*locale_codes)


def set_default_locale(code: str) -> None:
    """Sets the default locale.

    The default locale is assumed to be the language used for all strings
    in the system. The translations loaded from disk are mappings from
    the default locale to the destination locale. Consequently, you don't
    need to create a translation file for the default locale.
    """
    pass


def load_translations(directory: str, encoding: str | None = None) -> None:
    """Loads translations from CSV files in a directory.

    Translations are strings with optional Python-style named placeholders
    (e.g., ``My name is %(name)s``) and their associated translations.

    The directory should have translation files of the form ``LOCALE.csv``,
    e.g. ``es_GT.csv``. The CSV files should have two or three columns: string,
    translation, and an optional plural indicator. Plural indicators should
    be one of "plural" or "singular". A given string can have both singular
    and plural forms. For example ``%(name)s liked this`` may have a
    different verb conjugation depending on whether %(name)s is one
    name or a list of names. There should be two rows in the CSV file for
    that string, one with plural indicator "singular", and one "plural".
    For strings with no verbs that would change on translation, simply
    use "unknown" or the empty string (or don't include the column at all).

    The file is read using the `csv` module in the default "excel" dialect.
    In this format there should not be spaces after the commas.

    If no ``encoding`` parameter is given, the encoding will be
    detected automatically (among UTF-8 and UTF-16) if the file
    contains a byte-order marker (BOM), defaulting to UTF-8 if no BOM
    is present.

    Example translation ``es_LA.csv``::

        "I love you","Te amo"
        "%(name)s liked this","A %(name)s les gustó esto","plural"
        "%(name)s liked this","A %(name)s le gustó esto","singular"

    .. versionchanged:: 4.3
       Added ``encoding`` parameter. Added support for BOM-based encoding
       detection, UTF-16, and UTF-8-with-BOM.
    """
    pass


def load_gettext_translations(directory: str, domain: str) -> None:
    """Loads translations from `gettext`'s locale tree

    Locale tree is similar to system's ``/usr/share/locale``, like::

        {directory}/{lang}/LC_MESSAGES/{domain}.mo

    Three steps are required to have your app translated:

    1. Generate POT translation file::

        xgettext --language=Python --keyword=_:1,2 -d mydomain file1.py file2.html etc

    2. Merge against existing POT file::

        msgmerge old.po mydomain.po > new.po

    3. Compile::

        msgfmt mydomain.po -o {directory}/pt_BR/LC_MESSAGES/mydomain.mo
    """
    pass


def get_supported_locales() -> Iterable[str]:
    """Returns a list of all the supported locale codes."""
    pass


class Locale:
    """Object representing a locale.

    After calling one of `load_translations` or `load_gettext_translations`,
    call `get` or `get_closest` to get a Locale object.
    """

    _cache: dict[str, Locale] = {}

    @classmethod
    def get_closest(cls, *locale_codes: str) -> Locale:
        """Returns the closest match for the given locale code."""
        for code in locale_codes:
            if not code:
                continue
            code = code.replace("-", "_")
            parts = code.split("_")
            if len(parts) > 2:
                continue
            elif len(parts) == 2:
                code = parts[0].lower() + "_" + parts[1].upper()
            if code in _supported_locales:
                return cls.get(code)
            if parts[0].lower() in _supported_locales:
                return cls.get(parts[0].lower())
        return cls.get(_default_locale)

    @classmethod
    def get(cls, code: str) -> Locale:
        """Returns the Locale for the given locale code.

        If it is not supported, we raise an exception.
        """
        if code not in cls._cache:
            assert code in _supported_locales
            translations = _translations.get(code, None)
            if translations is None:
                locale: Locale = CSVLocale(code, {})
            elif _use_gettext:
                locale = GettextLocale(code, translations)
            else:
                locale = CSVLocale(code, translations)
            cls._cache[code] = locale
        return cls._cache[code]

    def __init__(self, code: str) -> None:
        self.code = code
        self.name = LOCALE_NAMES.get(code, {}).get("name", "Unknown")
        self.rtl = False
        for prefix in ["fa", "ar", "he"]:
            if self.code.startswith(prefix):
                self.rtl = True
                break

        # Initialize strings for date formatting
        _ = self.translate
        self._months = [
            _("January"),
            _("February"),
            _("March"),
            _("April"),
            _("May"),
            _("June"),
            _("July"),
            _("August"),
            _("September"),
            _("October"),
            _("November"),
            _("December"),
        ]
        self._weekdays = [
            _("Monday"),
            _("Tuesday"),
            _("Wednesday"),
            _("Thursday"),
            _("Friday"),
            _("Saturday"),
            _("Sunday"),
        ]

    def translate(
        self,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        """Returns the translation for the given message for this locale.

        If ``plural_message`` is given, you must also provide
        ``count``. We return ``plural_message`` when ``count != 1``,
        and we return the singular form for the given message when
        ``count == 1``.
        """
        raise NotImplementedError()

    def pgettext(
        self,
        context: str,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        raise NotImplementedError()

    def format_date(
        self,
        date: int | float | datetime.datetime,
        gmt_offset: int = 0,
        relative: bool = True,
        shorter: bool = False,
        full_format: bool = False,
    ) -> str:
        """Formats the given date.

        By default, we return a relative time (e.g., "2 minutes ago"). You
        can return an absolute date string with ``relative=False``.

        You can force a full format date ("July 10, 1980") with
        ``full_format=True``.

        This method is primarily intended for dates in the past.
        For dates in the future, we fall back to full format.

        .. versionchanged:: 6.4
           Aware `datetime.datetime` objects are now supported (naive
           datetimes are still assumed to be UTC).
        """
        pass

    def format_day(
        self, date: datetime.datetime, gmt_offset: int = 0, dow: bool = True
    ) -> str:
        """Formats the given date as a day of week.

        Example: "Monday, January 22". You can remove the day of week with
        ``dow=False``.
        """
        pass

    def list(self, parts: Any) -> str:
        """Returns a comma-separated list for the given list of parts.

        The format is, e.g., "A, B and C", "A and B" or just "A" for lists
        of size 1.
        """
        pass

    def friendly_number(self, value: int) -> str:
        """Returns a comma-separated number for the given integer."""
        pass


class CSVLocale(Locale):
    """Locale implementation using tornado's CSV translation format."""

    def __init__(self, code: str, translations: dict[str, dict[str, str]]) -> None:
        self.translations = translations
        super().__init__(code)

    def translate(
        self,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        if plural_message is not None:
            assert count is not None
            if count != 1:
                message = plural_message
                message_dict = self.translations.get("plural", {})
            else:
                message_dict = self.translations.get("singular", {})
        else:
            message_dict = self.translations.get("unknown", {})
        return message_dict.get(message, message)

    def pgettext(
        self,
        context: str,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        if self.translations:
            gen_log.warning("pgettext is not supported by CSVLocale")
        return self.translate(message, plural_message, count)


class GettextLocale(Locale):
    """Locale implementation using the `gettext` module."""

    def __init__(self, code: str, translations: gettext.NullTranslations) -> None:
        self.ngettext = translations.ngettext
        self.gettext = translations.gettext
        # self.gettext must exist before __init__ is called, since it
        # calls into self.translate
        super().__init__(code)

    def translate(
        self,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        if plural_message is not None:
            assert count is not None
            return self.ngettext(message, plural_message, count)
        else:
            return self.gettext(message)

    def pgettext(
        self,
        context: str,
        message: str,
        plural_message: str | None = None,
        count: int | None = None,
    ) -> str:
        """Allows to set context for translation, accepts plural forms.

        Usage example::

            pgettext("law", "right")
            pgettext("good", "right")

        Plural message example::

            pgettext("organization", "club", "clubs", len(clubs))
            pgettext("stick", "club", "clubs", len(clubs))

        To generate POT file with context, add following options to step 1
        of `load_gettext_translations` sequence::

            xgettext [basic options] --keyword=pgettext:1c,2 --keyword=pgettext:1c,2,3

        .. versionadded:: 4.2
        """
        if plural_message is not None:
            assert count is not None
            msgs_with_ctxt = (
                f"{context}{CONTEXT_SEPARATOR}{message}",
                f"{context}{CONTEXT_SEPARATOR}{plural_message}",
                count,
            )
            result = self.ngettext(*msgs_with_ctxt)
            if CONTEXT_SEPARATOR in result:
                # Translation not found
                result = self.ngettext(message, plural_message, count)
            return result
        else:
            msg_with_ctxt = f"{context}{CONTEXT_SEPARATOR}{message}"
            result = self.gettext(msg_with_ctxt)
            if CONTEXT_SEPARATOR in result:
                # Translation not found
                result = message
            return result
