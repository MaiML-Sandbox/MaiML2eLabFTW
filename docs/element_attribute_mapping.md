# MaiML protocolFileRootType → eLabFTW 要素・属性詳細マッピング表

> Status: Draft v0.1  
> 対象: MaiML Schema 1.0.0 / `protocolFileRootType`  
> 出力: eLabFTW Experiment Template  
> 生成単位: MaiML `<method>` 1件につきTemplate 1件

## 1. 表の読み方

| 記号 | 意味 |
|---|---|
| `1` | XSD上で必須・1件 |
| `1..*` | XSD上で必須・複数可 |
| `0..1` | 任意・最大1件 |
| `0..*` | 任意・複数可 |
| 表示 | eLabFTW UIに表示する |
| metadata | eLabFTW Metadata JSONに保持する |
| 添付 | eLabFTWの添付情報として保持する |
| 検証のみ | 変換判断に使うが、通常はUIへ表示しない |

本表の「必須・多重度」は、`MaiML-Schema-1_0`の以下のXSDに基づく。

- `maiml.xsd`
- `maiml-core.xsd`
- `maiml-document.xsd`
- `maiml-protocol.xsd`
- `maiml-pnml.xsd`
- `maiml-refTypes.xsd`
- `maiml-property.xsd`

## 2. スコープ解決規則

Template要素は、`protocol`、`method`、`program`の3階層に定義できる。
method単位のeLabFTW Templateを生成するときは、次の範囲を取り込む。

| MaiML上の定義位置 | 対象methodへの取込み |
|---|---|
| `protocol/materialTemplate`等 | すべてのmethodへ共通Templateとして取り込む |
| `method/materialTemplate`等 | そのmethodだけに取り込む |
| `method/program/materialTemplate`等 | そのprogramが属するmethodへ取り込む |

同じIDの要素を複数回作成せず、MaiMLの`id`をキーとして1件に統合する。
異なるIDで同じ`key`を持つfieldは別定義として保持する。

`templateRef`は参照関係としてmetadataへ保持し、参照先Templateのfieldを参照元へ
無条件に複製しない。

## 3. ルート要素

| XPath / 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 変換規則・欠損時 |
|---|---:|---|---:|---:|---|
| `/maiml` | 1 | 変換入力全体 | なし | あり | ルート要素。`xsi:type`が`protocolFileRootType`でなければ`INVALID_SOURCE_TYPE` |
| `/maiml/@xsi:type` | 実質必須 | Metadata JSON | なし | あり | `protocolFileRootType`のみMVP対象 |
| `/maiml/@version` | 1、固定`1.0` | Metadata JSON | なし | あり | `schema_version`として保持。不一致はXSDエラー |
| `/maiml/@features` | 0..1 | Metadata JSON | なし | あり | 文字列をそのまま保持。自動解釈しない |
| `/maiml/document` | 1 | Metadata、Main Text、添付 | 一部 | あり | 全method Templateへ共通の出典情報として複製 |
| `/maiml/protocol` | 1 | method変換元 | 一部 | あり | protocol配下のmethodごとに出力Templateを生成 |
| 元MaiMLファイル | 1 | Attachment | あり | あり | ファイル本体を添付し、SHA-256をmetadataへ保持 |

## 4. globalObjectContentGroup共通マッピング

`document`、`protocol`、`method`、`program`、`instruction`、各Template、`pnml`、
creator/vendor/owner/instrumentは、原則としてこの共通構造を持つ。

| 子要素 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `uuid` | 1 | Metadata JSON | 原則なし | あり | 要素の永続識別子。欠損・形式不正はXSDエラー |
| `insertion` | 0..* | Attachment | あり | あり | 7節の規則で処理 |
| `name` | 0..1 | Title、field label、Step titleまたは本文 | あり | あり | xs:QName。表示時は元文字列を維持 |
| `description` | 0..1 | Main Text、Step本文またはfield description | あり | あり | 所属要素に応じて配置 |
| `annotation` | 0..1 | Main TextまたはStep本文 | あり | あり | descriptionと区別してmetadataにも保持 |
| `property` | 0..* | Custom FieldまたはMetadata | 条件付き | あり | Template配下はCustom Field。それ以外は本文/metadata |
| `content` | 0..* | Custom FieldまたはMetadata | 条件付き | あり | Template配下はpropertyと同じ扱い |
| `childUri`等の暗号化グループ | 選択 | Metadata / unsupported | なし | あり | 復号しない。暗号化内容を必要とする場合は変換中止 |
| `xenc:EncryptedData` | 暗号化時1 | Metadata / unsupported | なし | あり | MVPでは復号・Custom Field化しない |

共通要素に`insertion/name/description/...`を持つ平文構造と暗号化グループはXSD上の
選択肢であり、同時には存在しない。

## 5. document

| XPath / 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 変換規則 |
|---|---:|---|---:|---:|---|
| `document/@id` | 1 | Metadata JSON | なし | あり | XML内参照用ID。eLabFTW IDには使用しない |
| `document/uuid` | 1 | Metadata JSON | なし | あり | `source_document_uuid`。method UUIDとの組で同一判定 |
| `document/name` | 0..1 | Main Textの出典欄 | あり | あり | Template titleの第一候補にはしない |
| `document/description` | 0..1 | Main Text | あり | あり | Protocol出典説明として表示 |
| `document/annotation` | 0..1 | Main Text | あり | あり | annotation見出し付きで表示 |
| `document/ds:Signature` | 0..1 | 元MaiML添付内 | なし | 状態のみ | 署名を変更しない。署名検証は別責務 |
| `document/creator` | 1..* | Main Text / Metadata | 一部 | あり | 名前等を出典情報として表示。Template所有者へ自動割当しない |
| `document/vendor` | 1..* | Main Text / Metadata | 一部 | あり | 装置・ソフトウェアのvendor情報として表示 |
| `document/owner` | 1..* | Main Text / Metadata | 一部 | あり | eLabFTWユーザーIDへ自動変換しない |
| `document/instrument` | 0..* | Main Text / Metadata | あり | あり | 使用装置候補として表示。Custom Field化はしない |
| `document/date` | 1 | Main Text / Metadata | あり | あり | 元文書日時。eLabFTW作成日時の上書きには使わない |
| `document/chain` | 0..* | Metadata JSON | なし | あり | uuid/hash/key/子chainを保持 |
| `document/parent` | 0..* | Metadata JSON | なし | あり | uuid/hash/key/子parentを保持 |

### 5.1 creator / vendor / owner / instrument共通

| 項目 | XSD | eLabFTW格納先 | 規則 |
|---|---:|---|---|
| `@id` | 1 | Metadata JSON | 元IDを保持 |
| `uuid` | 1 | Metadata JSON | 元UUIDを保持 |
| `name` | 0..1 | Main Text | 存在する場合に表示 |
| `description` | 0..1 | Main Text | 存在する場合に表示 |
| `annotation` | 0..1 | Main Text | 存在する場合に表示 |
| `property/content/insertion` | 0..* | Main Text / Metadata / Attachment | Template用Custom Fieldにはしない |
| `creator/vendorRef` | 1..* | Metadata JSON | `@ref`を保持。参照切れは`BROKEN_REFERENCE` |
| `creator/instrumentRef` | 0..* | Metadata JSON | `@ref`を保持。参照切れは`BROKEN_REFERENCE` |

## 6. protocol / method / program

### 6.1 protocol

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `protocol/@id` | 1 | Metadata JSON | なし | あり | 元IDを保持 |
| `protocol/uuid` | 1 | Metadata JSON | なし | あり | `source_protocol_uuid`として保持 |
| `protocol/name` | 0..1 | Main Text / title補助 | あり | あり | method名がない場合のTitle補助候補 |
| `protocol/description` | 0..1 | Main Text | あり | あり | 共通説明として全method Templateへ表示 |
| `protocol/annotation` | 0..1 | Main Text | あり | あり | 共通注記として表示 |
| `protocol/method` | 1..* | Experiment Template | あり | あり | 1 method＝1 Template |
| protocol直下の各Template | 各0..* | 全methodのCustom Fields | あり | あり | 共通fieldとして各method Templateへ取り込む |

### 6.2 method

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `method/@id` | 1 | Metadata JSON | なし | あり | 元IDを保持 |
| `method/uuid` | 1 | Metadata JSON | なし | あり | `source_method_uuid`。document UUIDとの組で同一判定 |
| `method/name` | 0..1 | Template Title | あり | あり | Titleの第一候補 |
| `method/description` | 0..1 | Main Text | あり | あり | method説明 |
| `method/annotation` | 0..1 | Main Text | あり | あり | method注記 |
| `method/pnml` | 1..* | Steps順序 / Metadata | 原則なし | あり | 単一PNMLは自動解析。複数PNMLは全体順が明示されなければYAMLを要求 |
| `method/program` | 1..* | Steps内容 / Main Text | 一部 | あり | instructionとTemplateを収集 |
| method直下の各Template | 各0..* | Custom Fields | あり | あり | 当該methodだけへ取り込む |

method名がない場合のTitle候補順は次とする。

1. `method/name`
2. `protocol/name + method/@id`
3. `Method <method/@id>`

### 6.3 program

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `program/@id` | 1 | Metadata JSON | なし | あり | instruction所属の判定に使用 |
| `program/uuid` | 1 | Metadata JSON | なし | あり | 元UUIDを保持 |
| `program/name` | 0..1 | Main Textのsection見出し | あり | あり | program区分をユーザーへ表示 |
| `program/description` | 0..1 | Main Text | あり | あり | program説明 |
| `program/annotation` | 0..1 | Main Text | あり | あり | program注記 |
| `program/instruction` | 1..* | Steps | あり | あり | transitionRefに従いStepへ展開 |
| program直下の各Template | 各0..* | Custom Fields | あり | あり | 当該method Templateへ取り込む。program所属もmetadata保持 |

## 7. insertion

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `insertion/uri` | 1 | Attachment / URL参照 | あり | あり | URIを解決できれば添付。解決不能は`UNRESOLVED_INSERTION` |
| `insertion/hash` | 1 | Attachment検証 / Metadata | なし | あり | 添付前に照合。値はbase64Binary |
| `insertion/hash/@method` | 0..1 | Metadata JSON | なし | あり | ハッシュ方式。欠損時は照合方式不明として警告 |
| `insertion/uuid` | 0..1 | Metadata JSON | なし | あり | 添付情報のUUIDとして保持 |
| `insertion/format` | 0..1 | Attachment media情報 / Metadata | 一部 | あり | MIME typeまたは形式文字列として保持 |

元MaiMLファイルは、XML内のinsertionとは別に`source_maiml`添付として必ず保持する。

## 8. PNML

### 8.1 pnml

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `pnml/@id` | 1 | Metadata JSON | なし | あり | グラフ識別子 |
| `pnml/uuid` | 1 | Metadata JSON | なし | あり | 元UUIDを保持 |
| `pnml/name` | 0..1 | Main Textの補助見出し | 条件付き | あり | 複数PNML時に表示可 |
| `pnml/description` | 0..1 | Main Text | 条件付き | あり | 存在時に工程説明として表示 |
| `pnml/place` | 1..* | 検証 / Metadata | なし | あり | transitionとの交互接続を検証 |
| `pnml/transition` | 1..* | Step工程位置 | 間接表示 | あり | instructionを配置する位置 |
| `pnml/arc` | 1..* | Step順序 | なし | あり | source/targetから順序を解決 |

### 8.2 place / transition

| 項目 | XSD | eLabFTW格納先 | 規則 |
|---|---:|---|---|
| `place/@id` | 1 | Metadata / 検証 | `placeRef/@ref`の参照先 |
| `place/name` | 0..1 | Metadata、必要に応じMain Text | UI Stepは作成しない |
| `place/description` | 0..1 | Metadata、必要に応じMain Text | 工程状態の説明 |
| `transition/@id` | 1 | Step metadata | Step配置キー |
| `transition/name` | 0..1 | Step title補助 | instruction名がない場合の補助候補 |
| `transition/description` | 0..1 | Step本文補助 | instruction本文を置換しない |

### 8.3 arc

| 項目 | XSD | eLabFTW格納先 | 規則 |
|---|---:|---|---|
| `arc/@id` | 1 | Metadata JSON | 元IDを保持 |
| `arc/@source` | 1 | 順序検証 / Metadata | 存在するplaceまたはtransitionを参照すること |
| `arc/@target` | 1 | 順序検証 / Metadata | 存在するplaceまたはtransitionを参照すること |
| `arc/name` | 0..1 | Metadata | 順序決定には使用しない |
| `arc/description` | 0..1 | Metadata | 補足情報として保持 |

以下を検出した場合は自動変換を中止し、Step順序YAMLを要求する。

- 分岐
- 合流
- 並列処理
- ループ
- 複数PNML間の全体順序が不明
- 開始点または終了点が一意でない
- 到達不能transition

YAMLを使用しても、存在しないID、参照切れ、instructionのないtransitionは許容しない。

## 9. instruction

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `instruction/@id` | 1 | Step metadata | なし | あり | Stepと元instructionの対応キー |
| `instruction/uuid` | 1 | Step metadata | なし | あり | UUIDが異なれば別instruction |
| `instruction/name` | 0..1 | Step title | あり | あり | title第一候補 |
| `instruction/description` | 0..1 | Step本文 | あり | あり | 操作説明 |
| `instruction/annotation` | 0..1 | Step本文 | あり | あり | 注記としてdescriptionと分離表示 |
| `instruction/property` | 0..* | Step本文 / Metadata | 条件付き | あり | Template fieldにはしない |
| `instruction/content` | 0..* | Step本文 / Metadata | 条件付き | あり | Template fieldにはしない |
| `instruction/insertion` | 0..* | Attachment / Step本文参照 | あり | あり | Stepとの関連をmetadata保持 |
| `instruction/transitionRef` | 1..* | Step配置 | なし | あり | 各ref位置へ同じinstruction内容のStepを生成 |

Step title候補順：

1. `instruction/name`
2. `transition/name`
3. `Instruction <instruction/@id>`

同一instructionが複数transitionを参照する場合、instruction定義は1件として保持し、
各transition位置に同じ内容のStepを生成する。

同一transitionを複数instructionが参照する場合、instruction UUIDごとにStepを生成する。
順序を一意に決定できなければYAMLの`instruction_ids`順を使用する。

## 10. materialTemplate / conditionTemplate / resultTemplate

3種類は同じXSD構造を持ち、roleと出力Groupだけが異なる。

| Template要素 | role | eLabFTW Group |
|---|---|---|
| `materialTemplate` | `material` | MATERIAL |
| `conditionTemplate` | `condition` | CONDITION |
| `resultTemplate` | `result` | RESULT |

### 10.1 共通要素・属性

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `@id` | 1 | Field metadata | なし | あり | Template識別子。スコープ間で統合キーに使用 |
| `uuid` | 1 | Field metadata | なし | あり | 元UUIDを保持 |
| `name` | 0..1 | Group内説明 / field label補助 | 条件付き | あり | Template名 |
| `description` | 0..1 | Group説明またはMain Text | あり | あり | Template説明 |
| `annotation` | 0..1 | Group説明またはMain Text | あり | あり | Template注記 |
| `property` | 0..* | 親roleのCustom Fields | あり | あり | 11節の規則で変換 |
| `content` | 0..* | 親roleのCustom Fields | あり | あり | propertyと同じ扱い |
| `insertion` | 0..* | Attachment | あり | あり | Templateとの関連をmetadata保持 |
| `placeRef` | 1..* | Metadata / 検証 | なし | あり | 対応placeを示す。参照切れはエラー |
| `templateRef` | 0..* | Metadata / 検証 | なし | あり | 参照関係を保持。fieldを自動複製しない |

### 10.2 placeRef

| 項目 | XSD | 規則 |
|---|---:|---|
| `placeRef/@id` | 1 | 参照要素自身のIDとしてmetadata保持 |
| `placeRef/@ref` | 1 | 対応するplace ID。参照切れは`BROKEN_REFERENCE` |
| `placeRef/@initialMarking` | 0..1 | booleanを保持。PNML開始状態の補助判定に利用可 |
| `placeRef/name` | 0..1 | metadata保持 |
| `placeRef/description` | 0..1 | metadata保持 |

### 10.3 templateRef / transitionRef

| 項目 | XSD | 規則 |
|---|---:|---|
| `@id` | 1 | 参照要素自身のIDとしてmetadata保持 |
| `@ref` | 1 | 参照先ID。参照切れは`BROKEN_REFERENCE` |
| `name` | 0..1 | metadata保持 |
| `description` | 0..1 | metadata保持 |

## 11. property / content

### 11.1 共通規則

`property`と`content`は抽象base typeを使用するため、実XMLでは具体的な`xsi:type`が
必要になる。両者とも`key`属性が必須である。

| 項目 | XSD | eLabFTW格納先 | 表示 | metadata | 規則 |
|---|---:|---|---:|---:|---|
| `property/@key` | 1 | Custom Fieldのsemantic key | 間接表示 | あり | xs:QName。表示labelとは分離して保持 |
| `content/@key` | 1 | Custom Fieldのsemantic key | 間接表示 | あり | propertyと同様 |
| `@xsi:type` | 具体型必須 | Custom Field type決定 | なし | あり | 型名をそのまま保持 |
| `description` | 0..1 | field description | あり | あり | 入力説明として使用 |
| `value` | 多くの型で0..1 | field初期値候補 | 条件付き | あり | プロトコル既定値として扱う。記録値とは区別 |
| `uncertainty` | 0..* | Metadata JSON | 原則なし | あり | MVPでは独立fieldへ展開しない |
| 子`property/content` | 0..* | Metadata / unsupported | 原則なし | あり | 入れ子の自動平坦化はしない |
| `formatString` | 型依存・任意 | Metadata JSON | なし | あり | 表示形式として保持 |
| `units` | 数値型等で任意 | Field label末尾`[unit]` | あり | あり | eLabFTW field名へ付加 |
| `scaleFactor` | 数値型等で任意 | Metadata JSON | なし | あり | 値を自動換算せず保持 |

### 11.2 表示ラベル

表示ラベルの決定順は次とする。

1. 変換設定で明示されたlabel
2. property/contentのdescriptionから短いlabelを明示取得できる場合
3. `key`のlocal part
4. 元の`key`文字列

単位がある場合は末尾へ付加する。

```text
<label> [<units>]
```

### 11.3 型マッピング

| MaiML具体型 | eLabFTW field type | 値の扱い |
|---|---|---|
| `booleanType` | `checkbox` | boolean既定値 |
| `dateTimeType` | `date` | 日付部分を表示。元dateTimeとformatStringはmetadata保持 |
| `decimalType`、`doubleType`、`floatType` | `number` | 数値。unitsをlabelへ付加 |
| 整数型各種 | `number` | 数値。範囲情報はmetadata保持 |
| `uriType`相当 | `url` | URI文字列 |
| `stringType`、`tokenType`、QName、ID/IDREF等 | `text` | 文字列 |
| UUID型 | `text` | UUID文字列 |
| 列挙値 | `text` | 選択UIへ変換せず文字列として保持 |
| list型 | `text` | 元の順序を維持した文字列表現。型情報をmetadata保持 |
| binary型 | `text`またはAttachment | 自動展開せず、用途に応じて報告 |
| 暗号化型 | unsupported | 復号しない |
| 未知の拡張型 | unsupported | API書込み前に報告。勝手にstring化しない |

### 11.4 同一keyと複数値

MaiML Schemaは、同じ親要素内で同一`key`を複数回使用することを禁止していない。
eLabFTWのCustom Field名は重複による識別が不安定になるため、次のように扱う。

- 1件目：通常label
- 2件目以降：`<label> #2`、`<label> #3`
- 元のkey、出現順、XPathをmetadataへ保持
- 同じkeyでも異なる`xsi:type`の場合は警告し、自動統合しない

## 12. Metadata JSONの対応情報

最低限、次を保持する。

```json
{
  "maiml": {
    "source_type": "protocolFileRootType",
    "source_document_id": "document-id",
    "source_document_uuid": "...",
    "source_protocol_id": "protocol-id",
    "source_protocol_uuid": "...",
    "source_method_id": "method-id",
    "source_method_uuid": "...",
    "schema_version": "1.0",
    "mapping_version": "1",
    "source_filename": "protocol.maiml",
    "source_sha256": "...",
    "pnml": [],
    "steps": [],
    "fields": [],
    "attachments": []
  }
}
```

### 12.1 Step metadata

各Stepについて次を保持する。

- eLabFTW Step順序
- program ID / UUID
- instruction ID / UUID
- transition ID
- instruction occurrence
- 順序決定元（`pnml`または`yaml`）
- source XPath

### 12.2 field metadata

各Custom Fieldについて次を保持する。

- eLabFTW field key/name
- role
- Group名
- Template種別、ID、UUID、定義スコープ
- `property`または`content`
- 元key
- 元`xsi:type`
- units
- formatString
- scaleFactor
- 出現順
- source XPath

## 13. API書込み前の必須検証

| 検証 | 失敗時 |
|---|---|
| XSD妥当性 | 書込み中止 |
| `protocolFileRootType` | 書込み中止 |
| document UUID | 書込み中止 |
| method UUID | 書込み中止 |
| document UUID + method UUIDの重複 | 上書きせず書込み中止 |
| IDの一意性 | 書込み中止 |
| 全IDREFの参照解決 | 書込み中止 |
| PNML arc接続 | 書込み中止 |
| transition順序 | 自動解決不能ならYAML要求 |
| transitionにinstructionがある | なければ書込み中止 |
| 同一transition内のinstruction順 | 不明ならYAML要求 |
| insertionの参照とhash | 解決不能または不一致なら書込み中止 |
| field型の変換可能性 | 必須fieldで不能なら書込み中止 |
| 元MaiML添付の準備 | 失敗なら書込み中止 |

## 14. 逆変換での利用

| 保存情報 | eLabFTW → MaiMLでの用途 |
|---|---|
| source document/method UUID | 使用したProtocolの同定 |
| 元MaiML添付 | 原本照合・再解析 |
| instruction/transition対応 | Step記録からevent/instructionを対応付ける |
| Template role | material/condition/result分類 |
| 元key / xsi:type / unit | property/content再構築 |
| placeRef / templateRef | 工程間関係の復元補助 |
| source XPath | 人による正誤確認 |
| YAML順序指定 | eLabFTW上で採用した線形表示順の説明 |

新しく作成されたeLabFTW ExperimentをMaiMLデータへ変換するときは、元Protocolの
document UUIDを新しいMaiML document UUIDとして再利用しない。新しいdocument UUIDを
発行し、元UUIDは来歴情報として保持する。

## 15. 変換レポート

各要素・属性を次のいずれかに分類して記録する。

| 状態 | 意味 |
|---|---|
| `mapped` | eLabFTWの表示要素へ変換 |
| `preserved_as_metadata` | UI表示せずmetadataへ保持 |
| `attached` | 添付情報として保持 |
| `warning` | 変換継続可能だが意味損失の可能性あり |
| `unsupported` | 安全に変換できない |
| `error` | API書込みを禁止する不整合 |

要素・属性を黙って破棄してはならない。

## 16. 実装時に固定する追加事項

本表に基づき、実装時に次を機械可読な設定・テストへ固定する。

1. MaiML具体型からeLabFTW field typeへの完全な型表
2. Metadata JSON Schema
3. field labelのエスケープと最大長
4. Main Textの見出しテンプレート
5. eLabFTW metadataサイズ・field数・Step数制限への対応
6. 複数PNMLを持つmethodのYAML例
7. protocol/method/program各スコープのTemplate fixture
8. 同一key複数出現のfixture
9. insertion hash検証fixture

