import collections
import collections.abc
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
class _Line(object):
    # to be overridden in subclasses or through the type_name argument
    TYPE = None

    def __init__(self, *args, type_name=None, **kwargs):
        self.fields = {f.name: f.default for f in self._field_defs}

        for k, v in zip(self.DEFAULT_FIELD_ORDER, args):
            self.fields[k] = v

        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                self.fields[k] = v

        if self.TYPE is None:
            self.TYPE = type_name

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
    def parse(cls, type_name, line, field_order=None):
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

        return cls(**fields, type_name=type_name)

class Unknown(_Line):
    value = _Field("Value", str, default="")

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

class CaseInsensitiveOrderedDict(collections.abc.MutableMapping):
    """A case insensitive ordered dictionary that preserves the original casing."""

    def __init__(self, *args, **kwargs):
        self._dict = collections.OrderedDict(*args, **kwargs)
        self._case_mapping = {key.lower(): key for key in self._dict}

        if len(self._case_mapping) != len(self._dict):
            raise ValueError("Duplicate keys provided for case insensitive dict")

    def __getitem__(self, key):
        return self._dict[self._case_mapping[key.lower()]]

    def __setitem__(self, key, value):
        if key.lower() not in self._case_mapping:
            self._case_mapping[key.lower()] = key
        self._dict[self._case_mapping[key.lower()]] = value

    def __delitem__(self, key):
        del self._dict[self._case_mapping[key.lower()]]
        del self._case_mapping[key.lower()]

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def __repr__(self):
        return repr(self._dict)

    def __str__(self):
        return str(self._dict)

class LineSection(collections.abc.MutableSequence):
    FORMAT_TYPE = "Format"
    line_parsers = None
    field_order = None

    def __init__(self, section, lines=None):
        self.section = section
        self._lines = [] if lines is None else lines

    def dump(self):
        yield "[{}]".format(self.section)

        if self.field_order is not None:
            yield "{}: {}".format(LineSection.FORMAT_TYPE, ", ".join(self.field_order))

        for line in self._lines:
            yield line.dump_with_type(self.field_order)

    def add_line(self, type_name, line):
        # field order is optional
        if type_name.lower() == LineSection.FORMAT_TYPE.lower():
            self.field_order = [field.strip() for field in line.split(",")]
        else:
            if self.line_parsers is not None and type_name.lower() not in self.line_parsers:
                raise ValueError("unexpected {} line in {}".format(type_name, self.section))

            parser = (self.line_parsers[type_name.lower()]
                      if self.line_parsers is not None
                      else Unknown)
            self._lines.append(parser.parse(type_name, line, self.field_order))

    def __getitem__(self, index):
        return self._lines[index]

    def __setitem__(self, index, val):
        self._lines[index] = val

    def __delitem__(self, index):
        del self._lines[index]

    def __len__(self):
        return len(self._lines)

    def insert(self, index, val):
        self._lines.insert(index, val)


class FieldSection(collections.abc.MutableMapping):
    # avoid metaclass conflict by keeping track of fields in a dict instead
    FIELDS = {}

    def __init__(self, section, fields=None):
        self.section = section
        self._fields = collections.OrderedDict() if fields is None else fields

    def add_line(self, field_name, field):
        if field_name in self.FIELDS:
            field = self.FIELDS[field_name].parse(field)

        self._fields[field_name] = field

    def dump(self):
        yield "[{}]".format(self.section)

        for k, v in self._fields.items():
            yield "{}: {}".format(k, _Field.dump(v))

    def __getitem__(self, key):
        return self._fields[key]

    def __setitem__(self, key, value):
        self._fields[key] = value

    def __delitem__(self, key):
        del self._fields[key]

    def __iter__(self):
        return iter(self._fields)

    def __len__(self):
        return len(self._fields)


class EventsSection(LineSection):
    field_order = Dialogue.DEFAULT_FIELD_ORDER
    line_parsers = {
        "dialogue": Dialogue,  # noqa: E241
        "comment":  Comment,   # noqa: E241
        "picture":  Picture,   # noqa: E241
        "sound":    Sound,     # noqa: E241
        "movie":    Movie,     # noqa: E241
        "command":  Command    # noqa: E241
    }

class StylesSection(LineSection):
    field_order = Style.DEFAULT_FIELD_ORDER
    line_parsers = {
        "style": Style
    }

class ScriptInfoSection(FieldSection):
    VERSION_ASS = "v4.00+"
    VERSION_SSA = "v4.00"
    FIELDS = {
        "ScriptType": _Field("ScriptType", str, default=VERSION_ASS),
        "PlayResX": _Field("PlayResX", int, default=640),
        "PlayResY": _Field("PlayResY", int, default=480),
        "WrapStyle": _Field("WrapStyle", int, default=0),
        "ScaledBorderAndShadow": _Field("ScaledBorderAndShadow", str, default="yes")
    }


@add_metaclass(_WithFieldMeta)
class Document(object):
    """ An ASS document. """
    SCRIPT_INFO_HEADER = "Script Info"
    STYLE_SSA_HEADER = "V4 Styles"
    STYLE_ASS_HEADER = "V4+ Styles"
    EVENTS_HEADER = "Events"

    SECTIONS = CaseInsensitiveOrderedDict({
        SCRIPT_INFO_HEADER: ScriptInfoSection,
        STYLE_SSA_HEADER: StylesSection,
        STYLE_ASS_HEADER: StylesSection,
        EVENTS_HEADER: EventsSection
    })

    # backwards compatibility
    script_type = ScriptInfoSection.FIELDS["ScriptType"]
    play_res_x = ScriptInfoSection.FIELDS["PlayResX"]
    play_res_y = ScriptInfoSection.FIELDS["PlayResY"]
    wrap_style = ScriptInfoSection.FIELDS["WrapStyle"]
    scaled_border_and_shadow = ScriptInfoSection.FIELDS["ScaledBorderAndShadow"]

    def __init__(self):
        """ Create an empty ASS document.
        """
        self.sections = CaseInsensitiveOrderedDict(
            [(header, self.SECTIONS[header](header)) for header in (self.SCRIPT_INFO_HEADER,
                                                                    self.STYLE_ASS_HEADER,
                                                                    self.EVENTS_HEADER)])
        self.fields = self.sections[self.SCRIPT_INFO_HEADER]
        self.styles = self.sections[self.STYLE_ASS_HEADER]
        self.events = self.sections[self.EVENTS_HEADER]

    @classmethod
    def parse_file(cls, f):
        """ Parse an ASS document from a file object.
        """
        doc = cls()

        section = None
        seen_sections = CaseInsensitiveOrderedDict()
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
                section_name = line[1:-1]
                # use existing section if available (pre-generated script info, styles, events)
                if section_name in doc.sections:
                    section = doc.sections[section_name]
                else:
                    section = doc.SECTIONS.get(section_name, LineSection)(section_name)

                seen_sections[section_name] = section
                continue

            if section is None:
                raise ValueError('Content outside of any section.')

            if ':' not in line:
                # illformed, ignore
                continue

            type_name, _, line = line.partition(":")
            line = line.lstrip()
            section.add_line(type_name, line)

        # append default sections not present in the parsed file
        for section_name, section in doc.sections.items():
            if section_name not in seen_sections:
                seen_sections[section_name] = section

        doc.sections = seen_sections

        return doc

    def dump_file(self, f):
        """ Dump this ASS document to a file object.
        """
        if getattr(f, 'encoding', 'utf_8_sig') != 'utf_8_sig':
            import warnings
            warnings.warn("It is recommended to write UTF-8 with BOM"
                          " using the 'utf_8_sig' encoding")

        for section in self.sections.values():
            f.write("\n".join(section.dump()))
            f.write("\n\n")

