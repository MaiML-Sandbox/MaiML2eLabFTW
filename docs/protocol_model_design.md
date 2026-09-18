# MaiML2eLabFTW ProtocolModel設計書

> Status: Draft v0.1  
> 対象リポジトリ: `MaiML-Sandbox/MaiML2eLabFTW`

## 1. 目的

MaiML `protocolFileRootType`のXML構造とeLabFTW REST APIの間に、eLabFTW非依存の
中間モデルを置く。本モデルは次の責務を持つ。

- MaiMLのmethod単位で変換対象を表現する
- PNMLの構造を保持する
- instructionとtransitionの多対多関係を保持する
- material / condition / result Templateのpropertyとcontentを統一的に表現する
- 自動順序解決またはYAML順序指定からStep計画を生成する
- API書込み前に全入力を検証する
- 元MaiMLおよび逆変換用メタデータへの参照を保持する

## 2. レイヤー構成

```text
MaiML XML
  ↓
MaiML Reader
  ↓
ProtocolDocumentModel
  ↓ method単位に分割
MethodProtocolModel
  ↓ PNML検証・順序解決
TemplatePlan
  ↓
eLabFTW Adapter
  ↓
Experiment Template
```

`ProtocolModel`はAPIレスポンス、HTTP、eLabFTW SDK型に依存しない。

## 3. モデル全体

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal


class TemplateRole(str, Enum):
    MATERIAL = "material"
    CONDITION = "condition"
    RESULT = "result"


class FieldSourceKind(str, Enum):
    PROPERTY = "property"
    CONTENT = "content"


class FieldType(str, Enum):
    NUMBER = "number"
    CHECKBOX = "checkbox"
    DATE = "date"
    URL = "url"
    TEXT = "text"


@dataclass(frozen=True)
class SourceIdentity:
    document_uuid: str
    method_uuid: str
    schema_version: str | None = None
    source_filename: str | None = None
    source_sha256: str | None = None


@dataclass(frozen=True)
class SourceRef:
    element_kind: str
    element_id: str | None
    xpath: str | None = None


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    label: str
    role: TemplateRole
    source_kind: FieldSourceKind
    field_type: FieldType
    source_ref: SourceRef
    semantic_key: str | None = None
    unit: str | None = None
    description: str | None = None
    required: bool = False
    default_value: Any | None = None
    enum_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TemplateDefinition:
    template_id: str
    role: TemplateRole
    source_ref: SourceRef
    fields: tuple[FieldDefinition, ...] = ()
    place_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class InstructionDefinition:
    instruction_id: str
    title: str
    body: str
    transition_refs: tuple[str, ...]
    source_ref: SourceRef


@dataclass(frozen=True)
class PlaceNode:
    place_id: str
    source_ref: SourceRef


@dataclass(frozen=True)
class TransitionNode:
    transition_id: str
    source_ref: SourceRef


@dataclass(frozen=True)
class ArcEdge:
    arc_id: str
    source_id: str
    target_id: str
    source_ref: SourceRef


@dataclass(frozen=True)
class PnmlGraph:
    places: tuple[PlaceNode, ...]
    transitions: tuple[TransitionNode, ...]
    arcs: tuple[ArcEdge, ...]


@dataclass(frozen=True)
class ProgramDefinition:
    program_id: str
    title: str | None
    description: str | None
    instructions: tuple[InstructionDefinition, ...]
    templates: tuple[TemplateDefinition, ...]
    source_ref: SourceRef


@dataclass(frozen=True)
class MethodProtocolModel:
    source: SourceIdentity
    title: str
    description: str | None
    method_source_ref: SourceRef
    programs: tuple[ProgramDefinition, ...]
    pnml_graphs: tuple[PnmlGraph, ...]
    templates: tuple[TemplateDefinition, ...]
    attachments: tuple[AttachmentDefinition, ...] = ()


@dataclass(frozen=True)
class ProtocolDocumentModel:
    document_uuid: str
    schema_version: str | None
    methods: tuple[MethodProtocolModel, ...]
    original_file: Path
    original_sha256: str
```

## 4. 添付情報

```python
@dataclass(frozen=True)
class AttachmentDefinition:
    attachment_id: str
    name: str
    source_kind: Literal["insertion", "source_maiml"]
    source_ref: SourceRef
    path: Path | None = None
    uri: str | None = None
    sha256: str | None = None
    media_type: str | None = None
```

制約：

- `path`と`uri`の少なくとも一方が必要
- 元MaiMLは`source_kind="source_maiml"`で必ず1件保持
- insertionの参照先を確認できない場合はAPI書込み前にエラー
- ハッシュがMaiMLに記録されている場合は添付前に照合

## 5. Step計画

PNMLとinstructionをそのままAPIへ渡さず、検証済みの`StepPlan`へ変換する。

```python
class StepOrderSource(str, Enum):
    PNML = "pnml"
    YAML = "yaml"


@dataclass(frozen=True)
class StepDefinition:
    ordinal: int
    transition_id: str
    instruction_id: str
    title: str
    body: str
    occurrence: int


@dataclass(frozen=True)
class StepPlan:
    source: StepOrderSource
    steps: tuple[StepDefinition, ...]
```

`occurrence`は、同じinstructionが複数transitionに配置される場合の出現番号とする。

例：Instruction AがT1とT3を参照する場合：

| ordinal | transition | instruction | occurrence |
|---:|---|---|---:|
| 1 | T1 | A | 1 |
| 2 | T2 | B | 1 |
| 3 | T3 | A | 2 |

## 6. eLabFTW作成計画

API書込み前に、最終的なTemplate全体を`TemplatePlan`へ確定する。

```python
@dataclass(frozen=True)
class CustomFieldPlan:
    field_id: str
    label: str
    group_name: Literal["MATERIAL", "CONDITION", "RESULT"]
    field_type: FieldType
    required: bool
    value: Any | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class TemplatePlan:
    source: SourceIdentity
    title: str
    body: str
    fields: tuple[CustomFieldPlan, ...]
    steps: StepPlan
    attachments: tuple[AttachmentDefinition, ...]
    metadata: dict[str, Any]
```

`TemplatePlan`が正常に構築できた後でのみeLabFTW APIを呼び出す。

## 7. property / contentの統一

`property`と`content`は、Reader層でどちらも`FieldDefinition`へ変換する。
違いは`source_kind`で保持する。

| 親Template | role | Custom Field Group |
|---|---|---|
| materialTemplate | material | MATERIAL |
| conditionTemplate | condition | CONDITION |
| resultTemplate | result | RESULT |

contentに名前がない場合、親Template内の出現順から安定したIDを生成する。

```text
<template-id>__content_001
<template-id>__content_002
```

生成したID、出現順、元XPathをMetadata JSONへ保持する。

## 8. 型変換

```python
MAIML_TO_ELABFTW_FIELD_TYPE = {
    "doubleType": FieldType.NUMBER,
    "booleanType": FieldType.CHECKBOX,
    "dateTimeType": FieldType.DATE,
    "uriType": FieldType.URL,
}
```

- 列挙値は`FieldType.TEXT`
- その他は`FieldType.TEXT`
- 単位は表示ラベル末尾へ`[unit]`として付加
- 元の型、key、unit、列挙定義はMetadata JSONへ保持

## 9. PNML検証規則

自動順序解決は、次の全条件を満たす場合だけ成功する。

1. arcのsource / targetがすべて存在する
2. placeとtransitionが交互に接続される
3. 開始点と終了点を一意に決定できる
4. 各中間ノードの有効な次ノードが1件だけである
5. 循環が存在しない
6. すべてのtransitionを開始点から到達できる
7. すべてのtransitionに1件以上のinstructionが対応する
8. 同一transitionに複数instructionがある場合、その順序を決定できる

3～6を満たさない場合は、YAMLによる明示順序を要求する。ただし、YAMLが指定されても
存在しないID/refやinstruction欠損は許容しない。

## 10. instruction展開規則

### 10.1 1 instruction → 複数transition

instruction定義は1件のまま保持し、参照する各transition位置へ同じ内容のStepを生成する。

### 10.2 1 transition ← 複数instruction

UUIDの異なるinstructionごとにStepを生成する。順序がMaiMLから確定しない場合は、
YAMLの`instruction_ids`順を使用する。

### 10.3 instructionのないtransition

`MissingInstructionError`として変換を中止する。空Stepは生成しない。

## 11. Metadata JSON

最低限、次の構造を生成する。

```json
{
  "maiml": {
    "source_type": "protocolFileRootType",
    "source_document_uuid": "...",
    "source_method_uuid": "...",
    "source_filename": "protocol.maiml",
    "source_sha256": "...",
    "schema_version": "1.0",
    "mapping_version": "1",
    "steps": [],
    "fields": [],
    "attachments": []
  }
}
```

eLabFTWが採番するTemplate IDやExperiment IDをMaiML UUIDで置き換えない。

## 12. 検証結果と例外

```python
class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    source_ref: SourceRef | None = None
    details: dict[str, Any] = field(default_factory=dict)
```

初期エラーコード：

| code | 条件 |
|---|---|
| `INVALID_SOURCE_TYPE` | protocolFileRootTypeではない |
| `MISSING_DOCUMENT_UUID` | document UUIDがない |
| `MISSING_METHOD_UUID` | method UUIDがない |
| `DUPLICATE_SOURCE` | document UUID + method UUIDが既存Templateと一致 |
| `BROKEN_REFERENCE` | ID/refの参照先がない |
| `INVALID_PNML` | PNML接続が不正 |
| `AMBIGUOUS_STEP_ORDER` | 分岐・並列等で順序を決定できない |
| `PNML_CYCLE` | ループを検出 |
| `MISSING_INSTRUCTION` | transitionにinstructionがない |
| `AMBIGUOUS_INSTRUCTION_ORDER` | 同一transition内のinstruction順が不明 |
| `INVALID_ORDER_FILE` | YAMLがスキーマ不適合 |
| `ORDER_SOURCE_MISMATCH` | YAMLのdocument/method UUIDが不一致 |
| `UNSUPPORTED_FIELD_TYPE` | 安全にField化できない型 |
| `UNRESOLVED_INSERTION` | insertionの実体・参照先を解決できない |
| `API_WRITE_FAILED` | eLabFTW API書込み失敗 |
| `ROLLBACK_FAILED` | 補償削除失敗 |

ERRORが1件でもあれば、API書込みを開始しない。

## 13. サービス境界

```python
class ProtocolReader:
    def read(self, path: Path) -> ProtocolDocumentModel: ...


class PnmlOrderResolver:
    def resolve(
        self,
        method: MethodProtocolModel,
        override: StepOrderOverride | None = None,
    ) -> StepPlan: ...


class TemplatePlanner:
    def build(
        self,
        document: ProtocolDocumentModel,
        method: MethodProtocolModel,
        steps: StepPlan,
        *,
        step_order_file_sha256: str | None = None,
    ) -> TemplatePlan: ...
    # document is required in addition to method: Metadata JSONの source
    # (document_id / protocol_id / protocol_uuid / features) はProtocolDocumentModel
    # にしか無く、method単体からは復元できないため。


class DuplicateDetector:
    def find_existing(self, source: SourceIdentity) -> int | None: ...


class ElabftwTemplateWriter:
    def create(self, plan: TemplatePlan) -> int: ...
    def rollback(self, template_id: int) -> None: ...
```

Reader、Resolver、PlannerはeLabFTW APIへアクセスしない。

## 14. 推奨ディレクトリ

```text
maiml2elabftw/
  core/
    models.py
    errors.py
    validation.py
  adapters/
    maiml/
      reader.py
    elabftw/
      client.py
      writer.py
  ordering/
    pnml.py
    override.py
    step_order.schema.json
  mapping/
    fields.py
    planner.py
  reporting/
    report.py
  cli.py
```

## 15. 最小テスト

1. 1 methodから1 TemplatePlanを生成
2. 複数methodを別々のTemplatePlanへ分割
3. 直列PNMLをarc順に解決
4. 分岐、合流、並列、ループを拒否
5. YAML指定で明示順を解決
6. YAMLのUUID不一致を拒否
7. instruction欠損transitionを拒否
8. 同一instructionを複数transitionへ展開
9. 同一transitionの複数instructionを指定順に展開
10. property/contentを親TemplateのGroupへ配置
11. dateTimeTypeをdateへ変換
12. 列挙値をtextへ変換
13. 単位を表示名へ付加し、Metadataにも保持
14. 元MaiMLをsource_maiml添付として計画
15. document UUID + method UUIDの重複を拒否
16. API失敗時に今回作成したTemplateを補償削除
17. 補償削除失敗時にTemplate IDをレポート
