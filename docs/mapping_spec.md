# MaiML protocolFileRootType → eLabFTW Experiment Template マッピング仕様書

> Status: Draft v0.2 — MVP方針確定版  
> Target repository: `MaiML-Sandbox/MaiML2eLabFTW`

## 1. 目的

MaiML `protocolFileRootType` に記載された計測分析プロトコルを、eLabFTWの
Experiment Templateへ変換する。ユーザーがプロトコルに沿った構造化入力と
自由記述を併用して実験記録を作成できることを目的とする。

本仕様では、将来の `eLabFTW / ELN → Rule / LLM → MaiML` 変換を考慮し、
MaiMLの意味情報、UUID、参照関係および変換元ファイルを保持する。

完全なXML round-tripではなく、プロトコルが意図した実験上の意味を維持する
semantic round-tripを目標とする。

## 2. 前提

`protocolFileRootType`は、実データ`<data>`および`<eventLog>`を持たず、
`<document>`と`<protocol>`を中心に計測分析手順を表現する。

MaiML Protocolでは、主に以下を利用する。

- `<method>`
- `<program>`
- `<pnml>`
- `<place>`
- `<transition>`
- `<arc>`
- `<instruction>`
- `<materialTemplate>`
- `<conditionTemplate>`
- `<resultTemplate>`

eLabFTW Experiment Templateでは、主に以下を利用する。

- Title
- Main Text
- Custom Fields
- Custom Field Groups
- Steps
- Tags
- Metadata JSON
- Attachments

eLabFTWへの書き込みにはRead/Write権限のAPIキーを使用する。

## 3. 基本原則

### 3.1 method単位でテンプレートを作成する

1つのMaiML `<method>`から、1つのeLabFTW Experiment Templateを作成する。
1つのprotocolファイルに複数のmethodが存在する場合は、method数分の
Experiment Templateを作成する。

テンプレートの変換元を識別するキーは、次の組み合わせとする。

```text
source_document_uuid + source_method_uuid
```

document UUIDだけでは、同一ファイル内の複数methodを区別できないため、
同一判定には使用しない。

### 3.2 表示用情報と逆変換用情報を分離する

ユーザーに表示する名称・説明・入力欄と、MaiMLへ戻すための識別情報を分離する。
MaiML固有のID、ref、role、key、unit等はeLabFTWのMetadata JSONへ保持する。

### 3.3 MaiMLのID / refを失わない

PNMLを含むMaiMLの関係性はID / refに依存する。変換時には、少なくとも以下を
Metadata JSONへ保持する。

- source document UUID
- source method UUID
- program ID / UUID
- instruction ID / UUID
- place ID
- transition ID
- arc source / target
- `placeRef`
- `transitionRef`
- `templateRef`
- Template ID / UUID
- property key
- content識別情報
- role
- unit
- MaiML schema version
- mapping version

### 3.4 ユーザーが定義した分類を正とする

MATERIAL、CONDITION、RESULTの分類は、科学的意味を推測して自動再分類しない。
MaiML上の所属および明示されたマッピングを正として扱う。

Custom Field Group名とMaiML上のroleは概念上別であり、その対応はMetadata JSONにも
明示する。

### 3.5 自由記述欄を残す

構造化入力だけで実験記録を完結させず、Main TextおよびStep本文に自由記述を
許容する。自由記述は将来のRule Engine / LLMによる解析対象とする。

## 4. 基本マッピング

| MaiML | eLabFTW Experiment Template | 方針 |
|---|---|---|
| `protocolFileRootType` | 1個以上のTemplate | method単位で分割 |
| `<document>` | Metadata JSON、添付 | UUID・作成情報を保持し、元MaiMLも添付 |
| `<protocol>` | Templateの出典情報 | protocol情報をMetadata JSONへ保持 |
| `<method>` | Template全体 | 1 method＝1 Template |
| `<program>` | Main Text / Metadata JSON | 工程の所属情報を保持 |
| `<pnml>` | Steps順序 / Metadata JSON | UIへ直接描画せず、順序決定と関係保持に利用 |
| `<place>` | TemplateとStepの関係 | Metadata JSONへ保持 |
| `<transition>` | Stepの工程位置 | arcから順序を決定 |
| `<arc>` | Step順序・入出力関係 | Metadata JSONへ保持 |
| `<instruction>` | Step | transitionRefの位置へ展開 |
| `<materialTemplate>` | MATERIAL Group | property/contentを入力欄へ変換 |
| `<conditionTemplate>` | CONDITION Group | property/contentを入力欄へ変換 |
| `<resultTemplate>` | RESULT Group | property/contentを入力欄へ変換 |
| `<property>` | Custom Field | 親TemplateのGroupへ配置 |
| `<content>` | Custom Field | propertyと同じ扱い。親TemplateのGroupへ配置 |
| `<insertion>` | Attachment | 添付情報として保持 |
| その他の説明情報 | Main Text / Step本文 | ユーザー向け説明として表示 |

## 5. Custom Field Group

初期実装では、以下のGroupを使用する。

```text
MATERIAL
CONDITION
RESULT
```

### 5.1 propertyとcontent

`property`と`content`は同じ変換経路でCustom Fieldへ変換する。配置先は親Templateに
よって決定する。

| MaiML | 配置先 |
|---|---|
| `materialTemplate/property` | MATERIAL Group |
| `materialTemplate/content` | MATERIAL Group |
| `conditionTemplate/property` | CONDITION Group |
| `conditionTemplate/content` | CONDITION Group |
| `resultTemplate/property` | RESULT Group |
| `resultTemplate/content` | RESULT Group |

Custom Fieldの表示名を直接MaiMLの意味識別子として使用せず、元のTemplate ID、
property key、content識別情報、role、型、単位をMetadata JSONへ保持する。

contentに明示的なkeyまたは名称がない場合は、親Template内で一意になるように
`content_001`、`content_002`のような安定した仮キーを割り当て、その対応を
Metadata JSONへ記録する。

### 5.2 insertion

`insertion`は添付情報として扱う。URL参照、ファイル名、ハッシュ値、元のID/ref等を
可能な範囲で保持する。添付できない参照は勝手に破棄せず、変換不能として報告する。

## 6. 型変換

| MaiMLの値型 | eLabFTW Custom Field |
|---|---|
| 数値型 / `doubleType` | `number` |
| boolean / `booleanType` | `checkbox` |
| date / `dateTimeType` | `date` |
| URI / `uriType` | `url` |
| 列挙値 | `text`。列挙値を文字列として保持 |
| 一般文字列 | `text` |
| 配列・複雑型 | Main TextまたはMetadata JSON。自動展開しない |

単位はCustom Field名へ付加する。

```text
AcceleratingVoltage [kV]
Temperature [degC]
Duration [min]
```

表示名とは別に、元のfield keyとunitをMetadata JSONへ保持する。

## 7. PNMLからStepsへの変換

### 7.1 自動変換の対象

自動変換は単純な直列PNMLだけを対象とする。

1. PNMLのarcをたどる。
2. placeとtransitionの接続を検証する。
3. transitionの実行順を一意に決定する。
4. transitionに関連するinstructionをeLabFTW Stepへ展開する。

分岐、合流、並列処理、ループまたは順序を一意に決定できない構造を、勝手に
線形化してはならない。

### 7.2 複雑なPNML

次のいずれかを検出した場合、APIへの書き込み前に自動変換を中止する。

- 分岐
- 合流
- 並列処理
- ループ
- 接続不良
- 複数の有効なtransition順序

エラーメッセージでは、Step順序を定義するYAMLの入力を要求する。

### 7.3 Step順序YAML

PNMLから順序を一意に決定できない場合、またはユーザーが明示的な順序を指定する
場合は、次のようなYAMLを使用する。

```yaml
version: 1

document_uuid: "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
method_uuid: "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy"

step_order:
  - transition_id: "transition-1"
  - transition_id: "transition-3"
  - transition_id: "transition-2"
```

YAML使用時も次を検証する。

- document UUIDとmethod UUIDが入力MaiMLと一致すること
- 指定されたtransitionが存在すること
- transitionの重複がないこと
- 必要なtransitionの指定漏れがないこと
- 各transitionにinstructionが存在すること

YAMLはPNMLの意味を変更するものではなく、eLabFTWの線形Stepsへ表示する順序を
明示する補助情報として扱う。

## 8. transitionとinstruction

### 8.1 基本規則

- instruction定義はMaiML上のUUID単位で1件として解釈する。
- eLabFTW Stepは、instructionが参照するtransitionの位置ごとに生成する。
- instruction参照が存在しないtransitionは変換対象外ではなく、入力不備としてエラーにする。

### 8.2 1つのinstructionが複数transitionを参照する場合

instruction定義は1件のまま保持し、同じ内容のeLabFTW Stepを各transition位置に
生成する。同じ操作を工程中で繰り返し実施するケースとして扱う。

例：

```text
Instruction A → T1, T3
Instruction B → T2
PNML順序       T1 → T2 → T3
```

生成結果：

| Step | transition | instruction |
|---:|---|---|
| 1 | T1 | Instruction A |
| 2 | T2 | Instruction B |
| 3 | T3 | Instruction A |

### 8.3 1つのtransitionを複数instructionが参照する場合

UUIDが異なるinstructionが同じtransitionを参照する場合、存在するinstruction数分の
Stepを、そのtransition位置に生成する。

同一transition内でのinstruction順序をMaiMLから一意に決定できない場合は、
YAMLによるinstruction順序の指定を要求する。YAMLスキーマの詳細設計では、
`transition_id`ごとに`instruction_ids`を順序付きで指定できる構造を追加する。

## 9. Main TextとStep本文

property、content、insertion以外の説明情報は、所属に応じてTemplateのMain Text
またはStep本文へ出力する。

- method / program全体の説明：Main Text
- instructionの説明・操作手順：Step本文
- 変換不能な構造化値：本文へ自動退避せず、変換レポートへ記録

Main TextとStep本文には、実験者が自由記述を追記できる領域を残す。

## 10. 逆変換用Metadata JSON

表示用Custom Fieldとは分離して、MaiML由来情報をMetadata JSONへ保持する。

概念例：

```json
{
  "maiml": {
    "source_type": "protocolFileRootType",
    "source_document_uuid": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "source_method_uuid": "yyyyyyyy-yyyy-yyyy-yyyy-yyyyyyyyyyyy",
    "schema_version": "1.0",
    "mapping_version": "1",
    "source_filename": "protocol.maiml"
  }
}
```

各StepおよびCustom Fieldについても、元のinstruction、transition、Template、
property/contentとの対応を保持する。

## 11. 元MaiMLの保持

変換元のMaiMLファイルそのものをeLabFTW Templateの添付情報として保持する。
これにより、Metadata JSONや表示用フィールドに誤りが疑われる場合でも、原本との
照合、再変換およびマッピング検証を可能にする。

添付前に、必要に応じてファイルハッシュを算出しMetadata JSONへ保持する。

## 12. eLabFTW IDとMaiML UUID

eLabFTWのTemplate IDおよびExperiment IDはeLabFTW側が採番する整数であり、
MaiML document UUIDを主IDとして設定しない。

識別子の役割を次のように分離する。

| 識別子 | 用途 |
|---|---|
| eLabFTW Template ID | eLabFTWが採番するTemplate識別子 |
| source document UUID | 元MaiML Protocolファイルの識別子 |
| source method UUID | method単位の変換元識別子 |
| eLabFTW Experiment ID | Templateから作成された実験ごとの識別子 |
| 出力MaiML document UUID | 実験記録をMaiMLへ変換するときに新規発行 |

元のdocument UUIDを、Templateから作成された各実験のdocument UUIDとして再利用しては
ならない。元UUIDは`source_protocol_document_uuid`として来歴情報に保持する。

## 13. API作成・同一判定・上書き禁止

### 13.1 事前検証

APIへ書き込む前に、以下をすべて検証する。

- XMLの読込みと必要に応じたXSD検証
- methodの存在
- UUID / ID / refの整合性
- PNML構造またはYAML順序指定
- transitionとinstructionの対応
- Custom Fieldへ変換可能な型
- 添付対象の存在
- 同一変換元Templateの不存在

### 13.2 同一判定

既存TemplateのMetadata JSONを調べ、次の組み合わせが一致するTemplateを同一と判定する。

```text
source_document_uuid + source_method_uuid
```

同一Templateが存在する場合は、新規作成も更新も行わずエラーにする。エラーには既存の
eLabFTW Template IDを含める。

### 13.3 上書き禁止

- 既存Templateを自動更新しない。
- 同一判定されたTemplateを上書きしない。
- 部分的に同じCustom FieldやStepが存在してもマージしない。
- 再作成する場合は、利用者が既存Templateを明示的に整理した後に実行する。

## 14. 部分作成時の取り消し

複数APIリクエストの途中で失敗した場合は、今回の実行で新規作成したTemplateを削除し、
作成前の状態へ戻す補償処理を行う。

想定処理順：

```text
事前検証
  ↓
Template作成
  ↓
Metadata設定
  ↓
Custom Fields設定
  ↓
Steps設定
  ↓
元MaiMLを添付
  ↓
完了
```

途中で失敗した場合：

1. 作成済みTemplateの削除を試行する。
2. 元のAPIエラーを保持する。
3. 削除結果を変換レポートへ記録する。
4. 削除にも失敗した場合は、残存Template IDと手動削除が必要であることを明示する。

複数methodを変換する場合は、処理単位を記録する。MVPでは、1ファイル内のmethod群を
一括処理として扱い、途中で失敗した場合は、その実行で作成済みの全Templateの削除を
試行する。

## 15. 変換結果レポート

各MaiML要素の処理結果を次の3分類で記録する。

- `mapped`：eLabFTWの表示要素へ変換済み
- `preserved_as_metadata`：表示せずMetadata JSONへ保持
- `unsupported`：変換できず、利用者の確認が必要

`unsupported`を黙って破棄してはならない。MVPでは、必須要素または工程順序に関する
`unsupported`が存在する場合、APIへの書き込みを中止する。

## 16. 往復変換の目標

```text
MaiML Protocol
      ↓
eLabFTW Template
      ↓
eLabFTW Experiment
      ↓
ELN Interpretation
      ↓
MaiML Data
```

目標は、完全なXMLの再現ではなく、Protocolが意図した意味、工程、入力分類、
参照関係および原記録への追跡可能性を維持することである。

## 17. MVP実装範囲

MVPでは以下を実装する。

1. `protocolFileRootType`の読込み
2. method単位の中間`ProtocolModel`生成
3. 単純直列PNMLの検証とtransition順序解決
4. YAMLによるStep順序指定
5. instructionからStepsへの展開
6. material / condition / result TemplateのCustom Field化
7. property / contentのCustom Field化
8. insertionおよび元MaiMLの添付
9. Metadata JSONへのMaiML識別情報の保持
10. 同一判定と上書き防止
11. eLabFTW REST API v2によるTemplate作成
12. 失敗時の補償削除
13. 変換結果レポート

初期実装では、次を自動変換対象外とする。

- YAML指定のない分岐・合流・並列・ループ
- 対応が解決できないID / ref
- instructionのないtransition
- eLabFTW Custom Fieldへ安全に変換できない複雑型
- 実体または参照先を確認できないinsertion

## 18. 次の設計作業

実装着手前に、次を詳細化する。

1. `ProtocolModel`のクラス設計
2. Step順序YAMLの正式スキーマ
3. Metadata JSONの正式スキーマ
4. eLabFTW API呼出し順序と補償削除手順
5. element / attribute単位の詳細マッピング表
6. エラーコードと変換レポート形式
7. 合成MaiML fixtureと回帰テスト方針

