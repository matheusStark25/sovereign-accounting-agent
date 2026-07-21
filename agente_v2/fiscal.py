from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict

import json

try:
    from lxml import etree  # type: ignore[reportMissingImports]
except Exception:
    etree = None

try:
    import jsonschema  # type: ignore[reportMissingImports]
except Exception:
    jsonschema = None


class FiscalExporter(ABC):
    @abstractmethod
    def export(self, payload: Dict[str, Any]) -> bytes:
        raise NotImplementedError()


class ESocialExporter(FiscalExporter):
    def __init__(self, xsd_path: str | None = None):
        self.xsd_path = xsd_path

    def export(self, payload: Dict[str, Any]) -> bytes:
        # naive mapping to XML; production should use templates and strict schemas
        root = etree.Element("eSocial") if etree else None
        if root is not None:
            assert etree is not None
            for k, v in payload.items():
                etree.SubElement(root, k).text = str(v)
            xml = etree.tostring(root, encoding="utf-8", xml_declaration=True)
            # validate if XSD provided
            if self.xsd_path and etree:
                assert etree is not None
                try:
                    schema = etree.XMLSchema(etree.parse(self.xsd_path))
                    doc = etree.fromstring(xml)
                    schema.assertValid(doc)
                except Exception:
                    raise
            return xml
        # fallback to JSON bytes
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class DCTFWebExporter(FiscalExporter):
    def __init__(self, schema: Dict[str, Any] | None = None):
        self.schema = schema

    def export(self, payload: Dict[str, Any]) -> bytes:
        # validate with jsonschema if available
        if self.schema and jsonschema:
            jsonschema.validate(payload, self.schema)
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")
