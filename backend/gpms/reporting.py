from datetime import date
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CONTENT = "http://schemas.openxmlformats.org/package/2006/content-types"
ET.register_namespace("", NS_MAIN)
ET.register_namespace("r", NS_REL)


def _tag(namespace, name):
    return f"{{{namespace}}}{name}"


def _cell_reference(column, row):
    label = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        label = chr(65 + remainder) + label
    return f"{label}{row}"


def make_xlsx(title, metadata, columns, rows):
    """Build a dependency-free, right-to-left XLSX containing text-only cells."""
    stream = BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        types = ET.Element(_tag(NS_CONTENT, "Types"))
        ET.SubElement(types, _tag(NS_CONTENT, "Default"), {"Extension": "rels", "ContentType": "application/vnd.openxmlformats-package.relationships+xml"})
        ET.SubElement(types, _tag(NS_CONTENT, "Default"), {"Extension": "xml", "ContentType": "application/xml"})
        ET.SubElement(types, _tag(NS_CONTENT, "Override"), {"PartName": "/xl/workbook.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"})
        ET.SubElement(types, _tag(NS_CONTENT, "Override"), {"PartName": "/xl/worksheets/sheet1.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"})
        ET.SubElement(types, _tag(NS_CONTENT, "Override"), {"PartName": "/xl/styles.xml", "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"})
        archive.writestr("[Content_Types].xml", ET.tostring(types, encoding="utf-8", xml_declaration=True))

        root_rels = ET.Element(_tag(NS_PKG_REL, "Relationships"))
        ET.SubElement(root_rels, _tag(NS_PKG_REL, "Relationship"), {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument", "Target": "xl/workbook.xml"})
        archive.writestr("_rels/.rels", ET.tostring(root_rels, encoding="utf-8", xml_declaration=True))

        workbook = ET.Element(_tag(NS_MAIN, "workbook"))
        sheets = ET.SubElement(workbook, _tag(NS_MAIN, "sheets"))
        ET.SubElement(sheets, _tag(NS_MAIN, "sheet"), {"name": "التقرير", "sheetId": "1", _tag(NS_REL, "id"): "rId1"})
        archive.writestr("xl/workbook.xml", ET.tostring(workbook, encoding="utf-8", xml_declaration=True))

        workbook_rels = ET.Element(_tag(NS_PKG_REL, "Relationships"))
        ET.SubElement(workbook_rels, _tag(NS_PKG_REL, "Relationship"), {"Id": "rId1", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet", "Target": "worksheets/sheet1.xml"})
        ET.SubElement(workbook_rels, _tag(NS_PKG_REL, "Relationship"), {"Id": "rId2", "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles", "Target": "styles.xml"})
        archive.writestr("xl/_rels/workbook.xml.rels", ET.tostring(workbook_rels, encoding="utf-8", xml_declaration=True))

        styles = ET.Element(_tag(NS_MAIN, "styleSheet"))
        fonts = ET.SubElement(styles, _tag(NS_MAIN, "fonts"), {"count": "1"})
        font = ET.SubElement(fonts, _tag(NS_MAIN, "font"))
        ET.SubElement(font, _tag(NS_MAIN, "sz"), {"val": "11"})
        ET.SubElement(font, _tag(NS_MAIN, "color"), {"theme": "1"})
        ET.SubElement(font, _tag(NS_MAIN, "name"), {"val": "Calibri"})
        ET.SubElement(font, _tag(NS_MAIN, "family"), {"val": "2"})
        ET.SubElement(font, _tag(NS_MAIN, "scheme"), {"val": "minor"})
        fills = ET.SubElement(styles, _tag(NS_MAIN, "fills"), {"count": "2"})
        fill = ET.SubElement(fills, _tag(NS_MAIN, "fill")); ET.SubElement(fill, _tag(NS_MAIN, "patternFill"), {"patternType": "none"})
        gray_fill = ET.SubElement(fills, _tag(NS_MAIN, "fill")); ET.SubElement(gray_fill, _tag(NS_MAIN, "patternFill"), {"patternType": "gray125"})
        borders = ET.SubElement(styles, _tag(NS_MAIN, "borders"), {"count": "1"})
        border = ET.SubElement(borders, _tag(NS_MAIN, "border"))
        for edge in ("left", "right", "top", "bottom", "diagonal"):
            ET.SubElement(border, _tag(NS_MAIN, edge))
        cell_style = ET.SubElement(styles, _tag(NS_MAIN, "cellStyleXfs"), {"count": "1"}); ET.SubElement(cell_style, _tag(NS_MAIN, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0"})
        cell_xfs = ET.SubElement(styles, _tag(NS_MAIN, "cellXfs"), {"count": "1"}); ET.SubElement(cell_xfs, _tag(NS_MAIN, "xf"), {"numFmtId": "0", "fontId": "0", "fillId": "0", "borderId": "0", "xfId": "0"})
        ET.SubElement(styles, _tag(NS_MAIN, "cellStyles"), {"count": "1"}).append(ET.Element(_tag(NS_MAIN, "cellStyle"), {"name": "Normal", "xfId": "0", "builtinId": "0"}))
        archive.writestr("xl/styles.xml", ET.tostring(styles, encoding="utf-8", xml_declaration=True))

        sheet = ET.Element(_tag(NS_MAIN, "worksheet"))
        views = ET.SubElement(sheet, _tag(NS_MAIN, "sheetViews"))
        ET.SubElement(views, _tag(NS_MAIN, "sheetView"), {"workbookViewId": "0", "rightToLeft": "1"})
        data = ET.SubElement(sheet, _tag(NS_MAIN, "sheetData"))
        all_rows = [[title], [metadata], [], columns, *rows]
        for row_number, values in enumerate(all_rows, 1):
            row = ET.SubElement(data, _tag(NS_MAIN, "row"), {"r": str(row_number)})
            for column_number, value in enumerate(values, 1):
                cell = ET.SubElement(row, _tag(NS_MAIN, "c"), {"r": _cell_reference(column_number, row_number), "t": "inlineStr"})
                inline = ET.SubElement(cell, _tag(NS_MAIN, "is"))
                text = ET.SubElement(inline, _tag(NS_MAIN, "t"))
                text.text = "" if value is None else str(value)
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(sheet, encoding="utf-8", xml_declaration=True))
    return stream.getvalue()
