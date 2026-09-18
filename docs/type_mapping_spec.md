# MaiML型 → eLabFTW Custom Field型 マッピング仕様

> Status: Draft v0.1  
> Machine-readable mapping: `maiml_to_elabftw_types.yaml`

## 1. 対象範囲

MaiML Schema 1.0.0の`maiml-property.xsd`に定義された、すべての具体的な
`propertyBaseType`派生型および`contentBaseType`派生型を対象とする。

XSDから確認した対象数は次のとおり。

| 区分 | 型数 |
|---|---:|
| property具体型 | 46 |
| content具体型 | 22 |
| 合計 | 68 |

未知の拡張型は文字列へ暗黙変換せず、`UNSUPPORTED_FIELD_TYPE`として停止する。

## 2. 基本方針

| MaiML分類 | eLabFTW | 方針 |
|---|---|---|
| 文字列・ID・QName・UUID・language | `text` | 元型をmetadata保持 |
| dateTime | `date` | 日付部分を表示し、元値をmetadata保持 |
| 数値scalar | `number` | unitsをfield名へ付加 |
| boolean scalar | `checkbox` | booleanとして保持 |
| URI scalar | `url` | URIとして保持 |
| binary scalar | `text` | 符号化文字列を維持し警告 |
| list | `text` | JSON配列文字列として順序を維持 |
| stringEnum | `text` | 候補値をmetadata保持 |
| propertyListType | metadataのみ | 複雑構造のため自動field化しない |

## 3. 数値型

次を`number`へ変換する。

- `decimalType`
- `doubleType`
- `floatType`
- `intType`
- `longType`
- `shortType`
- `byteType`
- `unsignedIntType`
- `unsignedLongType`
- `unsignedShortType`
- `unsignedByteType`

`units`はCustom Fieldの表示名へ`[unit]`として付加する。`formatString`、`units`、
`scaleFactor`はmetadataへ保持する。

`scaleFactor`は自動適用しない。元の値と係数の意味を変えないためである。

## 4. dateTime

`dateTimeType`はeLabFTWの`date`へ変換する。

```text
2026-09-17T12:34:56+09:00
↓
2026-09-17
```

時刻・タイムゾーンを失わないよう、元の値と`formatString`をmetadataへ保持する。
逆変換時は、ユーザーが日付を変更した場合の時刻補完を自動で推測せず、変換レポートに
明示する。

## 5. list型

eLabFTW Custom FieldにはMaiML list型と同等の型がないため、`text`へJSON配列として
格納する。

```json
["value1", "value2", "value3"]
```

空白区切り文字列にはしない。文字列値自体に空白が含まれる場合でも境界を維持するためである。

元のlist型、値順序、units、formatString、scaleFactorをmetadataへ保持する。

## 6. content型

MaiMLのcontent具体型はすべてlist型である。propertyと同じCustom Field変換経路を使用し、
値をJSON配列文字列として`text`へ格納する。

content固有属性をmetadataへ保持する。

- `axis`
- `size`
- `id`
- `ref`

`size`と実際の値数が矛盾する場合はAPI書込み前にエラーとする。

## 7. enum

ユーザー決定に従い、`stringEnumType`と`contentStringEnumType`はeLabFTWのselectへ
変換せず、`text`として出力する。

MaiML内の値候補と順序はmetadataへ保持し、逆変換時の検証に利用する。

## 8. binary

base64BinaryおよびhexBinaryは、元の符号化文字列を変更せず`text`として扱う。

binary値が大きく、eLabFTW Custom Fieldとして不適切な場合に備え、
`BINARY_AS_TEXT`警告を記録する。自動的に添付ファイルへ変換しない。

## 9. propertyListType

`propertyListType`は単純値を持たず、子property/contentによって複雑構造を表すため、
単一のCustom Fieldへ安全に変換できない。

MVPでは次の処理とする。

1. 構造全体をmetadataへ保持する。
2. Custom Fieldを自動生成しない。
3. `UNSUPPORTED_COMPLEX_FIELD`を変換レポートへ記録する。
4. 必須入力として利用される場合はAPI書込みを中止する。

## 10. valueがない場合

Protocol Templateでは、property/contentの`value`が省略されることがある。
この場合も型定義としてCustom Fieldを生成し、初期値なしとする。

valueが存在する場合は、プロトコル既定値として扱い、実験の実測値とは区別する。

## 11. uncertaintyと入れ子要素

`uncertainty`および子property/contentは、MVPでは独立したCustom Fieldへ平坦化しない。
構造をmetadataへ保持する。

意味を失う可能性がある場合は警告し、必須構造であれば変換を停止する。

## 12. 機械可読ファイルの使い方

実装では、`xsi:type`をキーとしてYAMLの`property_types`または`content_types`から
ルールを取得する。

```python
rule = mapping["property_types"].get(xsi_type)
if rule is None:
    raise UnsupportedFieldTypeError(xsi_type)
```

YAMLアンカーは記述重複を減らすために使用している。PyYAML等で読み込んだ後は、各型の
ルールが完全な辞書として展開される。

## 13. 実装時の検証条件

1. XSD内の全property具体型がYAMLに存在する
2. XSD内の全content具体型がYAMLに存在する
3. YAMLにXSDにない型がない
4. `supported: true`なら`elabftw_type`がnullでない
5. `supported: false`ならerror/warning方針が定義されている
6. 数値型はunits/formatString/scaleFactorをmetadata保持する
7. content型はaxis/size/id/refをmetadata保持する
8. list値はJSON配列としてround-tripできる
9. unknown型が自動的にtextへフォールバックしない
