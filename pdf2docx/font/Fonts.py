'''Extract fonts properties from PDF.

Font properties like font name, size are covered in :py:class:`~pdf2docx.text.TextSpan`, 
but more generic properties are required further:

* Font family name. The font name extracted and set in `TextSpan` might not valid when 
  directly used in MS Word, e.g. "ArialMT" should be "Arial". So, we need to get font
  family name, which should be accepted by MS Word, based on the font file itself.

* Font line height ratio. As line height = font_size * line_height_ratio, it's used to 
  calculate relative line spacing. In general, 1.12 is an approximate value to this ratio,
  but it's in fact a font-related value, especially for CJK font.
'''

import io
from collections import namedtuple 
from fontTools.ttLib import TTFont, TTLibError
from ..common.Collection import BaseCollection
from ..common.constants import (CJK_CODEPAGE_BITS, CJK_UNICODE_RANGE_BITS, 
                                    CJK_UNICODE_RANGES, DICT_FONT_LINE_HEIGHT)


Font = namedtuple('Font', ['name','line_height'])


class Fonts(BaseCollection):
    '''Extracted fonts properties from PDF.'''

    def get(self, font_name:str):
        '''Get matched font by font name, or return new font with same name 
        and default line height 1.20.'''
        normalized_font_name = font_name.replace(' ', '').upper()
        for font in self:
            name = font.name.replace(' ', '').upper()
            if normalized_font_name in name or name in normalized_font_name:
                return font
        
        return Font(name=font_name, line_height=1.2)


    @classmethod
    def extract(cls, fitz_doc):
        '''Extract fonts with ``PyMuPDF``.
        * Only embedded fonts (v.s. the base 14 fonts) can be extracted.
        * The extracted fonts may be invalid due to reason from PDF file itself.
        * Check a default font table for those failed case.
        '''        
        # get unique font references
        xrefs = set()
        for page in fitz_doc:
            for f in page.get_fonts(): xrefs.add(f[0])

        # process xref one by one
        default_fonts = cls.get_defult_fonts()
        fonts = []
        for xref in xrefs:
            valid = False
            basename, ext, _, buffer = fitz_doc.extract_font(xref)
            name = cls._normalized_font_name(basename)
            if ext != "n/a": # embedded fonts
                try:
                    tt = TTFont(io.BytesIO(buffer))
                except TTLibError as e:
                    tt = None
                    print(f'Font error {name}: {e}')

                if cls._is_valid(tt):
                    fonts.append(Font(
                        name=cls.get_font_family_name(tt),
                        line_height=cls.get_line_height_factor(tt)))
                    valid = True
                
            # check default if not valid
            if not valid:
                font = default_fonts.get(name)
                fonts.append(font)
        
        return cls(fonts)



    @classmethod
    def get_defult_fonts(cls):
        '''Get default font, e.g. base 14 font.'''
        fonts = [Font(name=name, line_height=f) for name, f in DICT_FONT_LINE_HEIGHT.items()]
        return Fonts(fonts)

    
    @staticmethod
    def _is_valid(tt_font:TTFont):
        if not tt_font: return False
        for key in ('name', 'hhea', 'head', 'OS/2'):
            if not tt_font.has_key(key): return False
        return True


    @staticmethod
    def _normalized_font_name(name):
        '''Normalize raw font name, e.g. BCDGEE+Calibri-Bold, BCDGEE+Calibri -> Calibri.'''
        return name.split('+')[-1].split('-')[0]

    
    @staticmethod
    def get_font_family_name(tt_font:TTFont):
        '''Get the font family name from the font's names table.

        https://gist.github.com/pklaus/dce37521579513c574d0
        '''
        name = family = ''
        FONT_SPECIFIER_NAME_ID = 4
        FONT_SPECIFIER_FAMILY_ID = 1

        for record in tt_font['name'].names:
            if b'\x00' in record.string:
                name_str = record.string.decode('utf-16-be')
            else:   
                name_str = record.string.decode('latin-1')

            if record.nameID == FONT_SPECIFIER_NAME_ID and not name:
                name = name_str
            elif record.nameID == FONT_SPECIFIER_FAMILY_ID and not family: 
                family = name_str

            if name and family: break

        # in case the font name is modified to pattern like BCDGEE+Calibri-Bold
        return Fonts._normalized_font_name(family)


    @staticmethod
    def get_line_height_factor(tt_font:TTFont):
        '''Calculate line height ratio based on ``hhea``.

        Fon non-CJK fonts::

            f = (hhea_ascent-hhea_descent+hhea_linegap) / units_per_em

        For CJK fonts::

            f = 1.3 * (hhea_ascent-hhea_descent) / units_per_em

        Read more:        
        * https://www.zhihu.com/question/23349103
        * https://github.com/source-foundry/font-line/blob/master/lib/fontline/metrics.py
        '''
        hhea = tt_font["hhea"]
        hhea_ascent = hhea.ascent
        hhea_descent = hhea.descent
        hhea_linegap = hhea.lineGap
        units_per_em = tt_font["head"].unitsPerEm

        cjk = Fonts.is_cjk_font(tt_font)

        hhea_total_height = hhea_ascent + abs(hhea_descent)
        hhea_btb_distance =  hhea_total_height + hhea_linegap

        distance = 1.3*hhea_total_height if cjk else 1.0*hhea_btb_distance

        return distance / units_per_em
    

    @staticmethod
    def is_cjk_font(tt_font:TTFont):
        '''Test font object to confirm that it meets our definition of a CJK font file.

        The definition is met if any of the following conditions are True:
        1. The font has a CJK code page bit set in the OS/2 table
        2. The font has a CJK Unicode range bit set in the OS/2 table
        3. The font has any CJK Unicode code points defined in the cmap table

        https://github.com/googlefonts/fontbakery/blob/main/Lib/fontbakery/profiles/shared_conditions.py
        '''
        os2 = tt_font["OS/2"]

        # OS/2 code page checks
        for _, bit in CJK_CODEPAGE_BITS.items():
            if os2.ulCodePageRange1 & (1 << bit):
                return True

        # OS/2 Unicode range checks
        for _, bit in CJK_UNICODE_RANGE_BITS.items():
            if bit in range(0, 32):
                if os2.ulUnicodeRange1 & (1 << bit):
                    return True

            elif bit in range(32, 64):
                if os2.ulUnicodeRange2 & (1 << (bit-32)):
                    return True

            elif bit in range(64, 96):
                if os2.ulUnicodeRange3 & (1 << (bit-64)):
                    return True

        # defined CJK Unicode code point in cmap table checks
        cmap = tt_font.getBestCmap()
        for unicode_range in CJK_UNICODE_RANGES:
            for x in range(unicode_range[0], unicode_range[1]+1):
                if int(x) in cmap:
                    return True

        # default, return False if the above checks did not identify a CJK font
        return False
