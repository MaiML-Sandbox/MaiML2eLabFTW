from __future__ import annotations

from hashlib import sha256
from importlib.resources import files
import json
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

import yaml

from ...core.errors import ConversionError, ErrorCode
from ...core.models import (
    ArcEdge,
    AttachmentDefinition,
    FieldDefinition,
    FieldSourceKind,
    FieldType,
    InstructionDefinition,
    MethodProtocolModel,
    PlaceNode,
    PlaceRefDefinition,
    PnmlGraph,
    ProgramDefinition,
    ProtocolDocumentModel,
    SourceIdentity,
    SourceRef,
    TemplateDefinition,
    TemplateRefDefinition,
    TemplateRole,
    TransitionNode,
)


NS = "http://www.maiml.org/schemas"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
Q = lambda name: f"{{{NS}}}{name}"


class ProtocolReader:
    """Read MaiML Schema 1.0 protocol files into the API-independent model."""

    def __init__(self) -> None:
        mapping_path = files("maiml2elabftw.resources").joinpath("maiml_to_elabftw_types.yaml")
        self._type_mapping = yaml.safe_load(mapping_path.read_text(encoding="utf-8"))

    def read(self, path: Path) -> ProtocolDocumentModel:
        path = Path(path)
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ConversionError(ErrorCode.INVALID_XML, f"cannot read XML: {exc}") from exc

        root_type = root.get(f"{{{XSI}}}type", "").split(":")[-1]
        if root.tag != Q("maiml") or root_type != "protocolFileRootType":
            raise ConversionError(ErrorCode.INVALID_SOURCE_TYPE, "root must be maiml with xsi:type=protocolFileRootType")
        if root.find(Q("data")) is not None or root.find(Q("eventLog")) is not None:
            raise ConversionError(ErrorCode.INVALID_SOURCE_TYPE, "protocol file must not contain data or eventLog")

        document = self._required_child(root, "document")
        protocol = self._required_child(root, "protocol")
        document_uuid = self._child_text(document, "uuid")
        if not document_uuid:
            raise ConversionError(ErrorCode.MISSING_DOCUMENT_UUID, "document/uuid is required")

        self._check_duplicate_ids(root)
        source_hash = sha256(path.read_bytes()).hexdigest()
        protocol_name = self._child_text(protocol, "name")
        shared_templates = self._parse_templates(protocol, "protocol")
        common_attachments = tuple(
            self._parse_insertions(document, document.get("id", "document"), path.parent)
            + self._parse_insertions(protocol, protocol.get("id", "protocol"), path.parent)
        )
        methods = tuple(
            self._parse_method(
                node,
                document_uuid=document_uuid,
                schema_version=root.get("version"),
                source_path=path,
                source_hash=source_hash,
                protocol_name=protocol_name,
                shared_templates=shared_templates,
                common_attachments=common_attachments,
            )
            for node in protocol.findall(Q("method"))
        )
        if not methods:
            raise ConversionError(ErrorCode.INVALID_XML, "protocol requires at least one method")
        return ProtocolDocumentModel(
            document_uuid=document_uuid,
            schema_version=root.get("version"),
            methods=methods,
            original_file=path,
            original_sha256=source_hash,
            document_id=document.get("id"),
            document_name=self._child_text(document, "name"),
            document_description=self._child_text(document, "description"),
            document_annotation=self._child_text(document, "annotation"),
            document_date=self._child_text(document, "date"),
            protocol_id=protocol.get("id"),
            protocol_uuid=self._child_text(protocol, "uuid"),
            protocol_name=protocol_name,
            protocol_description=self._child_text(protocol, "description"),
            protocol_annotation=self._child_text(protocol, "annotation"),
            features=root.get("features"),
        )

    def _parse_method(
        self,
        node: ET.Element,
        *,
        document_uuid: str,
        schema_version: str | None,
        source_path: Path,
        source_hash: str,
        protocol_name: str | None,
        shared_templates: tuple[TemplateDefinition, ...],
        common_attachments: tuple[AttachmentDefinition, ...],
    ) -> MethodProtocolModel:
        method_id = self._required_attr(node, "id")
        method_uuid = self._child_text(node, "uuid")
        if not method_uuid:
            raise ConversionError(ErrorCode.MISSING_METHOD_UUID, f"method {method_id} has no uuid")

        graphs = tuple(self._parse_pnml(item) for item in node.findall(Q("pnml")))
        if not graphs:
            raise ConversionError(ErrorCode.INVALID_PNML, f"method {method_id} has no PNML")
        programs = tuple(self._parse_program(item) for item in node.findall(Q("program")))
        if not programs:
            raise ConversionError(ErrorCode.INVALID_XML, f"method {method_id} has no program")

        method_templates = self._parse_templates(node, "method")
        program_templates = tuple(template for program in programs for template in program.templates)
        templates = self._deduplicate_templates(shared_templates + method_templates + program_templates)

        transition_ids = {item.transition_id for graph in graphs for item in graph.transitions}
        place_ids = {item.place_id for graph in graphs for item in graph.places}
        template_ids = {item.template_id for item in templates}
        for program in programs:
            for instruction in program.instructions:
                self._ensure_refs(instruction.transition_refs, transition_ids, "transitionRef", instruction.instruction_id)
        for template in templates:
            self._ensure_refs(
                tuple(item.place_id for item in template.place_refs), place_ids, "placeRef", template.template_id
            )
            self._ensure_refs(
                tuple(item.template_id for item in template.template_refs),
                template_ids,
                "templateRef",
                template.template_id,
            )

        attachments = list(common_attachments) + [
            AttachmentDefinition(
                attachment_id=f"source-maiml:{method_id}",
                name=source_path.name,
                source_kind="source_maiml",
                source_ref=SourceRef("method", method_id, f"/maiml/protocol/method[@id='{method_id}']"),
                path=source_path,
                sha256=source_hash,
                media_type="application/xml",
            )
        ]
        attachment_nodes = [node]
        attachment_nodes.extend(node.findall(Q("program")))
        attachment_nodes.extend(self._template_elements(node))
        for program_node in node.findall(Q("program")):
            attachment_nodes.extend(program_node.findall(Q("instruction")))
            attachment_nodes.extend(self._template_elements(program_node))
        for parent in attachment_nodes:
            attachments.extend(self._parse_insertions(parent, parent.get("id", method_id), source_path.parent))

        name = self._child_text(node, "name")
        title = name or (f"{protocol_name} - {method_id}" if protocol_name else f"Method {method_id}")
        return MethodProtocolModel(
            source=SourceIdentity(document_uuid, method_uuid, schema_version, source_path.name, source_hash),
            title=title,
            description=self._child_text(node, "description"),
            method_source_ref=SourceRef("method", method_id, f"/maiml/protocol/method[@id='{method_id}']"),
            programs=programs,
            pnml_graphs=graphs,
            templates=templates,
            attachments=tuple(attachments),
            annotation=self._child_text(node, "annotation"),
        )

    def _parse_program(self, node: ET.Element) -> ProgramDefinition:
        program_id = self._required_attr(node, "id")
        instructions = tuple(self._parse_instruction(item) for item in node.findall(Q("instruction")))
        if not instructions:
            raise ConversionError(ErrorCode.INVALID_XML, f"program {program_id} has no instruction")
        return ProgramDefinition(
            program_id=program_id,
            title=self._child_text(node, "name"),
            description=self._child_text(node, "description"),
            instructions=instructions,
            templates=self._parse_templates(node, "program"),
            source_ref=SourceRef("program", program_id),
            uuid=self._child_text(node, "uuid"),
            annotation=self._child_text(node, "annotation"),
        )

    def _parse_instruction(self, node: ET.Element) -> InstructionDefinition:
        instruction_id = self._required_attr(node, "id")
        refs = tuple(self._required_attr(item, "ref") for item in node.findall(Q("transitionRef")))
        if not refs:
            raise ConversionError(ErrorCode.MISSING_INSTRUCTION, f"instruction {instruction_id} has no transitionRef")
        description = self._child_text(node, "description") or ""
        annotation = self._child_text(node, "annotation")
        body = description + (f"\n\nAnnotation: {annotation}" if annotation else "")
        return InstructionDefinition(
            instruction_id=instruction_id,
            title=self._child_text(node, "name") or f"Instruction {instruction_id}",
            body=body,
            transition_refs=refs,
            source_ref=SourceRef("instruction", instruction_id),
            uuid=self._child_text(node, "uuid"),
            annotation=annotation,
        )

    def _parse_pnml(self, node: ET.Element) -> PnmlGraph:
        pnml_id = self._required_attr(node, "id")
        places = tuple(
            PlaceNode(
                self._required_attr(item, "id"),
                SourceRef("place", item.get("id")),
                self._child_text(item, "name"),
                self._child_text(item, "description"),
            )
            for item in node.findall(Q("place"))
        )
        transitions = tuple(
            TransitionNode(
                self._required_attr(item, "id"),
                SourceRef("transition", item.get("id")),
                self._child_text(item, "name"),
                self._child_text(item, "description"),
            )
            for item in node.findall(Q("transition"))
        )
        arcs = tuple(
            ArcEdge(
                self._required_attr(item, "id"),
                self._required_attr(item, "source"),
                self._required_attr(item, "target"),
                SourceRef("arc", item.get("id")),
                self._child_text(item, "name"),
                self._child_text(item, "description"),
            )
            for item in node.findall(Q("arc"))
        )
        return PnmlGraph(
            places, transitions, arcs, pnml_id, self._child_text(node, "uuid"),
            self._child_text(node, "name"), self._child_text(node, "description")
        )

    def _parse_templates(self, parent: ET.Element, scope: str) -> tuple[TemplateDefinition, ...]:
        result: list[TemplateDefinition] = []
        roles = {
            "materialTemplate": TemplateRole.MATERIAL,
            "conditionTemplate": TemplateRole.CONDITION,
            "resultTemplate": TemplateRole.RESULT,
        }
        for element_name, role in roles.items():
            for node in parent.findall(Q(element_name)):
                template_id = self._required_attr(node, "id")
                fields_out: list[FieldDefinition] = []
                for source_kind in (FieldSourceKind.PROPERTY, FieldSourceKind.CONTENT):
                    for index, field_node in enumerate(node.findall(Q(source_kind.value)), 1):
                        fields_out.append(self._parse_field(field_node, template_id, role, source_kind, index))
                result.append(
                    TemplateDefinition(
                        template_id=template_id,
                        role=role,
                        source_ref=SourceRef(element_name, template_id),
                        fields=tuple(fields_out),
                        place_refs=tuple(self._parse_place_ref(item) for item in node.findall(Q("placeRef"))),
                        template_refs=tuple(self._parse_template_ref(item) for item in node.findall(Q("templateRef"))),
                        uuid=self._child_text(node, "uuid"),
                        name=self._child_text(node, "name"),
                        description=self._child_text(node, "description"),
                        annotation=self._child_text(node, "annotation"),
                        scope=scope,
                    )
                )
        return tuple(result)

    def _parse_place_ref(self, node: ET.Element) -> PlaceRefDefinition:
        ref_id = self._required_attr(node, "id")
        return PlaceRefDefinition(
            ref_id=ref_id,
            place_id=self._required_attr(node, "ref"),
            initial_marking=self._parse_bool(node.get("initialMarking")),
            source_ref=SourceRef("placeRef", ref_id),
        )

    def _parse_template_ref(self, node: ET.Element) -> TemplateRefDefinition:
        ref_id = self._required_attr(node, "id")
        return TemplateRefDefinition(
            ref_id=ref_id,
            template_id=self._required_attr(node, "ref"),
            source_ref=SourceRef("templateRef", ref_id),
        )

    @staticmethod
    def _parse_bool(value: str | None) -> bool | None:
        if value is None:
            return None
        return value.strip().lower() in {"true", "1"}

    def _parse_field(
        self,
        node: ET.Element,
        template_id: str,
        role: TemplateRole,
        source_kind: FieldSourceKind,
        index: int,
    ) -> FieldDefinition:
        key = self._required_attr(node, "key")
        xsi_type = node.get(f"{{{XSI}}}type", "").split(":")[-1]
        section = "property_types" if source_kind is FieldSourceKind.PROPERTY else "content_types"
        rule = self._type_mapping.get(section, {}).get(xsi_type)
        if not rule or not rule.get("supported"):
            raise ConversionError(
                ErrorCode.UNSUPPORTED_FIELD_TYPE,
                f"{source_kind.value} {key} uses unsupported type {xsi_type or '(missing)'}",
            )
        raw_values = tuple((item.text or "") for item in node.findall(Q("value")))
        default_value = self._convert_value(raw_values, rule.get("strategy"))
        local_key = key.split(":")[-1]
        unit = node.get("units")
        return FieldDefinition(
            field_id=f"{template_id}__{source_kind.value}_{index:03d}",
            label=local_key,
            role=role,
            source_kind=source_kind,
            field_type=FieldType(rule["elabftw_type"]),
            source_ref=SourceRef(source_kind.value, None),
            semantic_key=key,
            maiml_type=xsi_type,
            unit=unit,
            description=self._child_text(node, "description"),
            default_value=default_value,
            enum_values=raw_values if xsi_type.endswith("EnumType") else (),
            source_attributes=tuple(sorted((self._attribute_name(k), v) for k, v in node.attrib.items())),
            raw_values=raw_values,
        )

    @staticmethod
    def _convert_value(values: tuple[str, ...], strategy: str | None):
        if not values:
            return None
        if strategy == "json_array_text":
            return json.dumps(values, ensure_ascii=False)
        value = values[0]
        if strategy == "scalar_number":
            try:
                return int(value)
            except ValueError:
                return float(value)
        if strategy == "scalar_boolean":
            return value.strip().lower() in {"true", "1"}
        if strategy == "date_part":
            return value[:10]
        return value

    def _parse_insertions(
        self, parent: ET.Element, owner_id: str, base_dir: Path | None = None
    ) -> list[AttachmentDefinition]:
        result: list[AttachmentDefinition] = []
        for index, node in enumerate(parent.findall(Q("insertion")), 1):
            uri = self._child_text(node, "uri")
            if not uri:
                raise ConversionError(ErrorCode.UNRESOLVED_INSERTION, f"insertion under {owner_id} has no URI")
            hash_node = node.find(Q("hash"))
            hash_value = (hash_node.text or "").strip() if hash_node is not None else None
            hash_method = hash_node.get("method") if hash_node is not None else None
            insertion_uuid = self._child_text(node, "uuid")
            result.append(
                AttachmentDefinition(
                    attachment_id=insertion_uuid or f"{owner_id}__insertion_{index:03d}",
                    name=Path(urlparse(uri).path).name or f"insertion_{index:03d}",
                    source_kind="insertion",
                    source_ref=SourceRef("insertion", insertion_uuid),
                    path=self._resolve_insertion_path(uri, base_dir),
                    uri=uri,
                    media_type=self._child_text(node, "format"),
                    hash_value=hash_value,
                    hash_method=hash_method,
                )
            )
        return result

    @staticmethod
    def _resolve_insertion_path(uri: str, base_dir: Path | None) -> Path | None:
        """Resolve an insertion's ``<uri>`` to a real local file next to the
        source .maiml, when the URI is a plain filesystem reference rather
        than a network location.

        Many MaiML files ship their insertions (images, raw data, ...) as
        sibling files referenced by a relative path such as
        ``./photo.tif``. Only a URI with no scheme (or ``file:``) is ever
        considered, and only when resolving it against the source file's
        own directory actually lands on a real file - a network URI
        (``http://``, ``https://``, ...) is never resolved here, and a
        dangling or genuinely external reference still surfaces as the
        existing "no local file to read" error at upload time instead of
        silently pointing at the wrong thing.
        """
        if base_dir is None:
            return None
        scheme = urlparse(uri).scheme
        if scheme not in ("", "file"):
            return None
        candidate = Path(unquote(urlparse(uri).path))
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        candidate = candidate.resolve()
        return candidate if candidate.is_file() else None

    @staticmethod
    def _deduplicate_templates(items: tuple[TemplateDefinition, ...]) -> tuple[TemplateDefinition, ...]:
        result: dict[str, TemplateDefinition] = {}
        for item in items:
            existing = result.get(item.template_id)
            if existing is not None and existing != item:
                raise ConversionError(ErrorCode.DUPLICATE_ID, f"template ID {item.template_id} is defined more than once")
            result[item.template_id] = item
        return tuple(result.values())

    @staticmethod
    def _ensure_refs(refs: tuple[str, ...], known: set[str], kind: str, owner: str) -> None:
        missing = sorted(set(refs) - known)
        if missing:
            raise ConversionError(ErrorCode.BROKEN_REFERENCE, f"{kind} under {owner} is unresolved", {"refs": missing})

    @staticmethod
    def _check_duplicate_ids(root: ET.Element) -> None:
        ids = [value for node in root.iter() if (value := node.get("id"))]
        duplicates = sorted(value for value in set(ids) if ids.count(value) > 1)
        if duplicates:
            raise ConversionError(ErrorCode.DUPLICATE_ID, "XML IDs must be unique", {"ids": duplicates})

    @staticmethod
    def _template_elements(parent: ET.Element) -> list[ET.Element]:
        return [item for name in ("materialTemplate", "conditionTemplate", "resultTemplate") for item in parent.findall(Q(name))]

    @staticmethod
    def _child_text(parent: ET.Element, name: str) -> str | None:
        node = parent.find(Q(name))
        if node is None or node.text is None:
            return None
        value = node.text.strip()
        return value or None

    @staticmethod
    def _required_child(parent: ET.Element, name: str) -> ET.Element:
        node = parent.find(Q(name))
        if node is None:
            raise ConversionError(ErrorCode.INVALID_XML, f"required element {name} is missing")
        return node

    @staticmethod
    def _required_attr(node: ET.Element, name: str) -> str:
        value = node.get(name)
        if not value:
            raise ConversionError(ErrorCode.INVALID_XML, f"{node.tag.split('}')[-1]}/@{name} is required")
        return value

    @staticmethod
    def _attribute_name(name: str) -> str:
        if name == f"{{{XSI}}}type":
            return "xsi:type"
        return name
