# MaiML2eLabFTW Metadata JSON Schema仕様

> Status: Draft v0.1  
> Schema: `maiml_metadata.schema.json`

## 1. 目的

MaiMLから生成したeLabFTW Experiment Templateに、逆変換・原本照合・重複判定に
必要な情報を機械可読な形式で保持する。

eLabFTW既存の`extra_fields`や`elabftw.extra_fields_groups`と共存できるよう、metadataの
トップレベルには`maiml`プロパティを追加する。トップレベルの他プロパティは許可するが、
`maiml`オブジェクト内は未知のプロパティを禁止する。

## 2. ルート構造

Group定義は`elabftw.extra_fields_groups`配下に置く（トップレベルの
`extra_fields_groups`ではない — eLabFTWはそれを無視し、全フィールドが
「デフォルトグループ」表示になる。公式ドキュメントと実サーバーの両方で確認済み）。

```json
{
  "extra_fields": {},
  "elabftw": {
    "extra_fields_groups": []
  },
  "maiml": {}
}
```

`maiml`には以下を必須とする。

- `source`
- `generator`
- `pnml`
- `steps`
- `fields`
- `attachments`
- `references`
- `conversion_summary`

## 3. source

変換元を一意に特定する。

同一Template判定には次の組を使用する。

```text
source.document_uuid + source.method_uuid
```

eLabFTWのTemplate IDおよびExperiment IDは、このUUIDで置換しない。

## 4. generator

変換ツールのバージョン、マッピング仕様のバージョン、生成日時、Step順序の決定元を
保持する。

`step_order_source`は`pnml`または`yaml`とする。YAMLを使用した場合は、設定ファイルの
SHA-256を`step_order_file_sha256`へ保持する。

## 5. pnml

methodに属するすべてのPNMLについて、以下を保持する。

- PNML ID / UUID
- place ID、name、description
- transition ID、name、description
- arc ID、source、target、name、description

これはeLabFTW上の線形Stepsだけでは失われる元グラフを追跡するために使用する。

## 6. steps

生成した各Stepについて、次を保持する。

- eLabFTW上の順序
- eLabFTW Step ID
- transition ID
- program ID
- instruction ID / UUID
- 同一instructionの出現番号
- 順序決定元
- 元要素のXPath

同じinstructionが複数transitionを参照する場合、同じinstruction ID / UUIDを持つ
複数Stepが、異なるtransition IDとoccurrenceを持つ。

## 7. fields

各Custom Fieldについて、次を保持する。

- eLabFTW上のfield名と型
- MATERIAL / CONDITION / RESULT Group
- MaiML role
- 元Templateの種別、ID、UUID、定義スコープ
- propertyまたはcontent
- 元keyと`xsi:type`
- unit、formatString、scaleFactor
- 同一key内の出現番号
- 元要素のXPath

表示名が変更されても、元keyおよび型からMaiMLの意味を追跡できる構造とする。

## 8. attachments

元MaiMLファイルを表す`source_maiml`が最低1件必要である。

XML内のinsertionは`source_kind="insertion"`として追加する。URI、UUID、元のhash、
実ファイルのSHA-256、formatを区別して保持する。

## 9. references

`placeRef`、`transitionRef`、`templateRef`を保持する。参照要素自身のIDと参照先IDを
分離する。`placeRef`だけが持つ`initialMarking`も保持する。

## 10. conversion_summary

変換結果の件数概要を保持する。

- `mapped`
- `preserved_as_metadata`
- `attached`
- `warnings`

詳細なエラーやログは実行時の変換レポートへ記録し、正常作成されたTemplateのmetadataには
件数概要だけを保存する。

## 11. Schemaだけでは検証しない規則

次はJSON Schemaだけでは完全に表現せず、Pythonの業務検証として実装する。

1. document UUID + method UUIDの重複確認
2. PNML内のID一意性
3. arc source / targetの存在確認
4. transitionRef / placeRef / templateRefの参照解決
5. `steps[].ordinal`が1から連続していること
6. `steps[].transition_id`がPNML内に存在すること
7. fieldのrole、group、template_kindの組合せ整合性
8. `template_scope="program"`時にprogram_idが存在すること
9. 添付ファイルのhash検証
10. `source.sha256`とsource_maiml添付のSHA-256一致

## 12. role整合表

| template_kind | role | group |
|---|---|---|
| `materialTemplate` | `material` | `MATERIAL` |
| `conditionTemplate` | `condition` | `CONDITION` |
| `resultTemplate` | `result` | `RESULT` |

この対応はユーザーが確定したMaiML分類を保持するものであり、field名や科学的意味から
自動的に変更しない。

