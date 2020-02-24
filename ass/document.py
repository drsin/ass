from datetime import timedelta
import itertools


class Color(object):
    """ Represents a color in the ASS format.
    """
    def __init__(self, r, g, b, a=0):
        """ Made up of red, green, blue and alpha components (in that order!).
        """
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    def to_int(self):
        return self.a + (self.b << 8) + (self.g << 16) + (self.r << 24)

    def to_ass(self):
        """ Convert this color to a Visual Basic (ASS) color code.
        """
        return "&H{a:02X}{b:02X}{g:02X}{r:02X}".format(**self.__dict__)

    @classmethod
    def from_ass(cls, v):
        """ Convert a Visual Basic (ASS) color code into an ``Color``.
        """
        if not v.startswith("&H"):
            raise ValueError("color must start with &H")

        rest = int(v[2:], 16)

        # AABBGGRR
        r = rest & 0xFF
        rest >>= 8

        g = rest & 0xFF
        rest >>= 8

        b = rest & 0xFF
        rest >>= 8

        a = rest & 0xFF

        return cls(r, g, b, a)

    def __repr__(self):
        return "{name}(r=0x{r:02x}, g=0x{g:02x}, b=0x{b:02x}, a=0x{a:02x})".format(
            name=self.__class__.__name__,
            r=self.r,
            g=self.g,
            b=self.b,
            a=self.a
        )


Color.WHITE = Color(255, 255, 255)
Color.RED = Color(255, 0, 0)
Color.BLACK = Color(0, 0, 0)


class _Field(object):
    _last_creation_order = -1

    def __init__(self, name, type, default=None):
        self.name = name
        self.type = type
        self.default = default

        _Field._last_creation_order += 1
        self._creation_order = self._last_creation_order

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return obj.fields.get(self.name, self.default)

    def __set__(self, obj, v):
        obj.fields[self.name] = v

    @staticmethod
    def dump(v):
        if v is None:
            return ""

        if isinstance(v, bool):
            return str(-int(v))

        if isinstance(v, timedelta):
            return _Field.timedelta_to_ass(v)

        if isinstance(v, float):
            return "{0:g}".format(v)

        if hasattr(v, "to_ass"):
            return v.to_ass()

        return str(v)

    def parse(self, v):
        if self.type is None:
            return None

        if self.type is bool:
            return bool(-int(v))

        if self.type is timedelta:
            return _Field.timedelta_from_ass(v)

        if hasattr(self.type, "from_ass"):
            return self.type.from_ass(v)

        return self.type(v)

    @staticmethod
    def timedelta_to_ass(td):
        r = int(td.total_seconds())

        r, secs = divmod(r, 60)
        hours, mins = divmod(r, 60)

        return "{hours:.0f}:{mins:02.0f}:{secs:02.0f}.{csecs:02}".format(
            hours=hours,
            mins=mins,
            secs=secs,
            csecs=td.microseconds // 10000
        )

    @staticmethod
    def timedelta_from_ass(v):
        secs_str, _, csecs = v.partition(".")
        hours, mins, secs = map(int, secs_str.split(":"))

        r = hours * 60 * 60 + mins * 60 + secs + int(csecs) * 1e-2

        return timedelta(seconds=r)


class _WithFieldMeta(type):
    def __new__(cls, name, bases, dct):
        newcls = type.__new__(cls, name, bases, dct)

        field_defs = []
        for base in bases:
            if hasattr(base, "_field_defs"):
                field_defs.extend(base._field_defs)
        field_defs.extend(sorted((f for f in dct.values() if isinstance(f, _Field)),
                                 key=lambda f: f._creation_order))
        newcls._field_defs = tuple(field_defs)

        field_mappings = {}
        for base in bases:
            if hasattr(base, "_field_mappings"):
                field_mappings.update(base._field_mappings)
        field_mappings.update({f.name: f for f in field_defs})
        newcls._field_mappings = field_mappings

        newcls.DEFAULT_FIELD_ORDER = tuple(f.name for f in field_defs)
        return newcls


def add_metaclass(metaclass):
    """
    Decorate a class to replace it with a metaclass-constructed version.

    Usage:

    @add_metaclass(MyMeta)
    class MyClass(object):
        ...

    That code produces a class equivalent to

    class MyClass(object, metaclass=MyMeta):
        ...

    on Python 3 or

    class MyClass(object):
        __metaclass__ = MyMeta

    on Python 2

    Requires Python 2.6 or later (for class decoration). For use on Python
    2.5 and earlier, use the legacy syntax:

    class MyClass(object):
        ...
    MyClass = add_metaclass(MyClass)

    Taken from six.py.
    https://bitbucket.org/gutworth/six/src/default/six.py
    """
    def wrapper(cls):
        orig_vars = cls.__dict__.copy()
        orig_vars.pop('__dict__', None)
        orig_vars.pop('__weakref__', None)
        for slots_var in orig_vars.get('__slots__', ()):
            orig_vars.pop(slots_var)
        return metaclass(cls.__name__, cls.__bases__, orig_vars)
    return wrapper


class Tag(object):
    """ A tag in ASS, e.g. {\\b1}. Multiple can be used like {\\b1\\i1}. """

    def __init__(self, name, params):
        self.name = name
        self.param = params

    def to_ass(self):
        if not self.params:
            params = ""
        elif len(self.params) == 1:
            params = params[0]
        else:
            params = ("("
                      + ",".join(_Field.dump(param) for param in self.params)
                      + ")")

        return "\\{name}{params}".format(name=self.name, params=params)

    @staticmethod
    def strip_tags(parts, keep_drawing_commands=False):
        text_parts = []

        it = iter(parts)

        for part in it:
            if isinstance(part, Tag):
                # if we encounter a \p1 tag, skip everything until we get to
                # \p0
                if not keep_drawing_commands and part.name == "p" and part.params == [1]:
                    for part2 in it:
                        if isinstance(part2, Tag) and part2.name == "p"and part2.params == [0]:
                            break
            else:
                text_parts.append(part)

        return "".join(text_parts)

    @classmethod
    def from_ass(cls, s):
        raise NotImplementedError


@add_metaclass(_WithFieldMeta)
class Document(object):
    """ An ASS document. """
    SCRIPT_INFO_HEADER = "[Script Info]"
    STYLE_SSA_HEADER = "[V4 Styles]"
    STYLE_ASS_HEADER = "[V4+ Styles]"
    EVENTS_HEADER = "[Events]"

    FORMAT_TYPE = "Format"

    VERSION_ASS = "v4.00+"
    VERSION_SSA = "v4.00"

    script_type = _Field("ScriptType", str, default=VERSION_ASS)
    play_res_x = _Field("PlayResX", int, default=640)
    play_res_y = _Field("PlayResY", int, default=480)
    wrap_style = _Field("WrapStyle", int, default=0)
    scaled_border_and_shadow = _Field("ScaledBorderAndShadow", str, default="yes")

    def __init__(self):
        """ Create an empty ASS document.
        """
        self.fields = {}

        self.styles = []
        self.styles_field_order = Style.DEFAULT_FIELD_ORDER

        self.events = []
        self.events_field_order = _Event.DEFAULT_FIELD_ORDER

    @classmethod
    def parse_file(cls, f):
        """ Parse an ASS document from a file object.
        """
        doc = cls()

        section = None
        for i, line in enumerate(f):
            if i == 0:
                bom_seqeunces = ("\xef\xbb\xbf", "\xff\xfe", "\ufeff")
                if any(line.startswith(seq) for seq in bom_seqeunces):
                    raise ValueError("BOM detected. Please open the file with the proper encoding,"
                                     " usually 'utf_8_sig'")

            line = line.strip()
            if not line or line.startswith(';'):
                continue

            if line.startswith('[') and line.endswith(']'):
                section = line
                field_order = None
                continue

            if section is None:
                raise ValueError('Content outside of any section.')

            if section.lower() == doc.SCRIPT_INFO_HEADER.lower():
                # [Script Info]
                if ':' not in line:
                    # illformed, ignore
                    continue

                field_name, _, field = line.partition(":")
                field = field.lstrip()

                if field_name in Document._field_mappings:
                    field = Document._field_mappings[field_name].parse(field)

                doc.fields[field_name] = field

            elif section.lower() in (doc.STYLE_SSA_HEADER.lower(),
                                     doc.STYLE_ASS_HEADER.lower()):
                # [V4 Styles] / [V4+ Styles]
                if ':' not in line:
                    continue

                type_name, _, line = line.partition(":")
                line = line.lstrip()

                if field_order is None:
                    # Format: ...
                    if type_name.lower() != Document.FORMAT_TYPE.lower():
                        raise ValueError("expected format line in styles")

                    field_order = [field.strip() for field in line.split(",")]
                    doc.styles_field_order = field_order
                else:
                    # Style: ...
                    if type_name.lower() != Style.TYPE.lower():
                        raise ValueError("expected style line in styles")

                    doc.styles.append(Style.parse(line, field_order))

            elif section.lower() == doc.EVENTS_HEADER.lower():
                # [Events]
                if ':' not in line:
                    continue

                type_name, _, line = line.partition(":")
                line = line.lstrip()

                if field_order is None:
                    # Format: ...
                    if type_name.lower() != Document.FORMAT_TYPE.lower():
                        raise ValueError("expected format line in events")

                    field_order = [field.strip() for field in line.split(",")]
                    doc.events_field_order = field_order
                else:
                    # Dialogue: ...
                    # Comment: ...
                    # etc.
                    doc.events.append(({
                        "Dialogue": Dialogue,  # noqa: E241
                        "Comment":  Comment,   # noqa: E241
                        "Picture":  Picture,   # noqa: E241
                        "Sound":    Sound,     # noqa: E241
                        "Movie":    Movie,     # noqa: E241
                        "Command":  Command    # noqa: E241
                    })[type_name].parse(line, field_order))

            else:
                # unknown sections
                continue

        return doc

    def dump_file(self, f):
        """ Dump this ASS document to a file object.
        """
        encoding = getattr(f, 'encoding')
        if encoding and encoding != 'utf_8_sig':
            import warnings
            warnings.warn("It is recommended to write UTF-8 with BOM"
                          " using the 'utf_8_sig' encoding")

        f.write(Document.SCRIPT_INFO_HEADER + "\n")
        for k in itertools.chain(
            (field for field in self.DEFAULT_FIELD_ORDER if field in self.fields),
            (field for field in self.fields if field not in self._field_mappings),
        ):
            f.write(k + ": " + _Field.dump(self.fields[k]) + "\n")
        f.write("\n")

        f.write(Document.STYLE_ASS_HEADER + "\n")
        f.write(Document.FORMAT_TYPE + ": " + ", ".join(self.styles_field_order) + "\n")
        for style in self.styles:
            f.write(style.dump_with_type(self.styles_field_order) + "\n")
        f.write("\n")

        f.write(Document.EVENTS_HEADER + "\n")
        f.write(Document.FORMAT_TYPE + ": " + ", ".join(self.events_field_order) + "\n")
        for event in self.events:
            f.write(event.dump_with_type(self.events_field_order) + "\n")
        f.write("\n")


@add_metaclass(_WithFieldMeta)
class _Line(object):
    def __init__(self, *args, **kwargs):
        self.fields = {f.name: f.default for f in self._field_defs}

        for k, v in zip(self.DEFAULT_FIELD_ORDER, args):
            self.fields[k] = v

        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                self.fields[k] = v

    def dump(self, field_order=None):
        """ Dump an ASS line into text format. Has an optional field order
        parameter in case you have some wonky format.
        """
        if field_order is None:
            field_order = self.DEFAULT_FIELD_ORDER

        return ",".join(_Field.dump(self.fields[field])
                        for field in field_order)

    def dump_with_type(self, field_order=None):
        """ Dump an ASS line into text format, with its type prepended. """
        return self.TYPE + ": " + self.dump(field_order)

    @classmethod
    def parse(cls, line, field_order=None):
        """ Parse an ASS line from text format. Has an optional field order
        parameter in case you have some wonky format.
        """
        if field_order is None:
            field_order = cls.DEFAULT_FIELD_ORDER

        parts = line.split(",", len(field_order) - 1)

        if len(parts) != len(field_order):
            raise ValueError("arity of line does not match arity of field order")

        fields = {}

        for field_name, field in zip(field_order, parts):
            if field_name in cls._field_mappings:
                field = cls._field_mappings[field_name].parse(field)
            fields[field_name] = field

        return cls(**fields)


class Style(_Line):
    """ A style line in ASS.
    """
    TYPE = "Style"

    name = _Field("Name", str, default="Default")
    fontname = _Field("Fontname", str, default="Arial")
    fontsize = _Field("Fontsize", float, default=20)
    primary_color = _Field("PrimaryColour", Color, default=Color.WHITE)
    secondary_color = _Field("SecondaryColour", Color, default=Color.RED)
    outline_color = _Field("OutlineColour", Color, default=Color.BLACK)
    back_color = _Field("BackColour", Color, default=Color.BLACK)
    bold = _Field("Bold", bool, default=False)
    italic = _Field("Italic", bool, default=False)
    underline = _Field("Underline", bool, default=False)
    strike_out = _Field("StrikeOut", bool, default=False)
    scale_x = _Field("ScaleX", float, default=100)
    scale_y = _Field("ScaleY", float, default=100)
    spacing = _Field("Spacing", float, default=0)
    angle = _Field("Angle", float, default=0)
    border_style = _Field("BorderStyle", int, default=1)
    outline = _Field("Outline", float, default=2)
    shadow = _Field("Shadow", float, default=2)
    alignment = _Field("Alignment", int, default=2)
    margin_l = _Field("MarginL", int, default=10)
    margin_r = _Field("MarginR", int, default=10)
    margin_v = _Field("MarginV", int, default=10)
    encoding = _Field("Encoding", int, default=1)


class _Event(_Line):
    layer = _Field("Layer", int, default=0)
    start = _Field("Start", timedelta, default=timedelta(0))
    end = _Field("End", timedelta, default=timedelta(0))
    style = _Field("Style", str, default="Default")
    name = _Field("Name", str, default="")
    margin_l = _Field("MarginL", int, default=0)
    margin_r = _Field("MarginR", int, default=0)
    margin_v = _Field("MarginV", int, default=0)
    effect = _Field("Effect", str, default="")
    text = _Field("Text", str, default="")


class Dialogue(_Event):
    """ A dialog event.
    """
    TYPE = "Dialogue"

    def parse_parts(self):
        parts = []

        current = []

        backslash = False

        it = iter(self.text)

        for c in it:
            if backslash:
                if c == "{":
                    current.append(c)
                else:
                    current.append("\\" + c)
                backslash = False
            elif c == "{":
                if current:
                    parts.append("".join(current))

                current = []

                tag_part = []

                for c2 in it:
                    if c2 == "}":
                        break
                    tag_part.append(c2)

                parts.append(Tag.from_ass("".join(tag_part)))
            elif c == "\\":
                backslash = True
            else:
                current.append(c)

        if backslash:
            current.append("\\")

        if current:
            parts.append("".join(current))

        return parts

    def tags_stripped(self):
        return Tag.strip_tags(self.parse())

    def unparse_parts(self, parts):
        self.text = "".join(n.dump() if isinstance(n, Tag) else n
                            for n in parts)


class Comment(_Event):
    """ A comment event.
    """
    TYPE = "Comment"


class Picture(_Event):
    """ A picture event. Not widely supported.
    """
    TYPE = "Picture"


class Sound(_Event):
    """ A sound event. Not widely supported.
    """
    TYPE = "Sound"


class Movie(_Event):
    """ A movie event. Not widely supported.
    """
    TYPE = "Movie"


class Command(_Event):
    """ A command event. Not widely supported.
    """
    TYPE = "Command"
