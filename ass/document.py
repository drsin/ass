from .data import _WithFieldMeta
from .section import ScriptInfoSection, FieldSection, StylesSection, EventsSection, LineSection
from ._util import CaseInsensitiveOrderedDict

from .data import *  # noqa: F40  # re-export for compatibility


def _section_property(header):
    def getter(self):
        return self.sections[header]

    def setter(self, value):
        section_type = self.SECTIONS[header]
        if isinstance(value, section_type):
            self.sections[header] = value
        else:
            self.sections[header].set_data(value)

    return property(getter, setter)


class Document(object, metaclass=_WithFieldMeta):
    """ An ASS document. """
    SCRIPT_INFO_HEADER = "Script Info"
    STYLE_SSA_HEADER = "V4 Styles"
    STYLE_ASS_HEADER = "V4+ Styles"
    EVENTS_HEADER = "Events"
    AEGISUB_PROJECT_HEADER = "Aegisub Project Garbage"

    SECTIONS = CaseInsensitiveOrderedDict({
        SCRIPT_INFO_HEADER: ScriptInfoSection,
        AEGISUB_PROJECT_HEADER: FieldSection,
        STYLE_SSA_HEADER: StylesSection,
        STYLE_ASS_HEADER: StylesSection,
        EVENTS_HEADER: EventsSection,
    })

    DEFAULT_SECTION_HEADERS = [SCRIPT_INFO_HEADER,
                               STYLE_ASS_HEADER,
                               EVENTS_HEADER]

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
            [(header, self.SECTIONS[header](header)) for header in self.DEFAULT_SECTION_HEADERS])

    fields = _section_property(SCRIPT_INFO_HEADER)
    styles = _section_property(STYLE_ASS_HEADER)
    events = _section_property(EVENTS_HEADER)

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
