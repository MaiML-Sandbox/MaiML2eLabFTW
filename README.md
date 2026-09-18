# MaiML2eLabFTW

MaiML `protocolFileRootType`からeLabFTW Experiment Templateを生成するための
非公式Pythonツールです。

## 現在の実装範囲

- method単位の中間モデル
- PNMLの単純直列順序の検証・解決
- Step順序YAMLによる明示順序
- instructionとtransitionの対応からStepPlanを生成
- 分岐・合流・ループ、参照切れ、instruction欠損の拒否
- `protocolFileRootType` XMLのReader
- protocol/method/programの3スコープからTemplateを収集
- property/contentの型対応表によるFieldDefinition変換
- placeRef/templateRef自身のidとinitialMarkingの保持
- TemplatePlanner（method+StepPlanからTemplatePlanを構築、Custom Field化、
  逆変換用Metadata JSON生成、`maiml_metadata.schema.json`によるAPI書込み前検証)
- `ElabftwClient`抽象化（eLabFTW REST APIへの唯一の窓口、Protocolとして定義。
  Custom FieldsとmaimlのmetadataはeLabFTW上で同じJSONに載るため、
  `set_custom_fields`は存在せず`set_metadata`一本化）
- `DuplicateDetector`（`source_document_uuid + source_method_uuid`による重複検出）
- `ElabftwTemplateWriter`（Template本体・Steps・統合metadata・添付の書込みと、
  失敗時に今回作成したTemplateだけを対象とする補償削除、補償削除失敗時の`ROLLBACK_FAILED`)
- `metadata_bundle.build_metadata_bundle`（eLabFTW自身の`metadata`に載せる
  **薄い**JSON―`extra_fields`・`elabftw.extra_fields_groups`・重複検出用の
  `maiml_source`(document_uuid/method_uuid/mapping_version/metadata_attachment)
  だけ―を1つに組み立て、Writerが`set_metadata`を1回だけ呼ぶことで、Custom
  Fieldsとmaiml_sourceがPATCHの競合で互いを消し合わないようにする。Group定義は
  `elabftw.extra_fields_groups`配下に置く必要があり、トップレベルの
  `extra_fields_groups`は無視されて全フィールドがデフォルトグループ表示になる
  ―実サーバー・公式ドキュメント双方で確認済み)
- `metadata_bundle.build_full_metadata_attachment`（PNML・Steps・全Fieldの
  ソース位置・attachments・references・conversion_summary・
  conversion_warningsを含む完全な逆変換record―以前はeLabFTWの`metadata`へ
  直接埋め込んでいたもの―を`maiml-metadata.json`という1つの添付ファイルとして
  生成する。埋め込んだままだと、eLabFTW自身のPDFエクスポートがこの内部情報を
  全展開してしまい、実データで12ページ超を占める問題があったため分離した)
- `HttpElabftwClient`（httpx実装。`Authorization`ヘッダーへ生のAPIキー、
  作成IDは`201`の`Location`ヘッダーから取得、404/409/422/429/5xxを別例外に区別、
  429と一時的な5xxのみ限定的に再試行、POSTと添付アップロードは無条件では再試行しない、
  TLS検証は標準で有効・`verify=False`の簡易な入口は用意しない)

insertionの`<uri>`がネットワークスキーム(`http://`等)を持たない相対/絶対パスで、
かつ.maimlファイルと同じディレクトリ基準で実在するファイルを指している場合は、
`ProtocolReader`がそれをローカルパスへ解決し、`HttpElabftwClient.upload_attachment`が
実際にアップロードします(`_resolve_insertion_path`)。実在しない場合や
外部URLの場合はこれまでどおり`path`が`None`のまま残り、アップロード時に
明確なエラーになります(黙って別のものを指すことはしない)。
また、対象eLabFTWサーバーの実際のバージョン・OpenAPI仕様に対する契約テスト・
実サーバーでの統合テスト（作成・確認・削除）はまだ実施していません。

**`metadata`はJSON文字列として送る**: 実サーバーでの検証により、
`experiments_templates.metadata`列へJSONオブジェクトをそのまま送ると
`500`（`Invalid JSON text ... for column 'experiments_templates.metadata'`、
MySQL/MariaDBエラー3140）で拒否されることを確認しました。
`HttpElabftwClient.set_metadata`は`json.dumps(metadata)`で文字列化してから
送信します（GET時に常に文字列で返ってくる`_parse_metadata_field`側の前提と
一致する挙動で、eLabFTWはこの列をAPI境界では終始、オブジェクトではなく
不透明な文字列として扱っているとみられます）。

**重複検出は`q`検索に依存しない**: eLabFTWの公式OpenAPI仕様により、
`q`パラメータは「title・body・elabid内の語を検索する」ものであり、metadata
（JSONカラム）の内容には一切到達しないことが確認できました。以前の
`find_duplicate`は`q=method_uuid`で候補を絞り込んでいたため、常に0件しか
返らず、同じMaiMLを何度実行しても重複として検出されず新規Templateが
作られ続けるバグがありました（実運用で同一ファイルが3回取り込まれた事例で
発覚）。

さらに実サーバーでの検証で、一覧API（`GET /experiments_templates`）自体が
`metadata`を一切返さないことも確認しました（`extended=1`を付けても付けなくても
`None`。`metadata`が返るのは個別取得`GET /experiments_templates/{id}`のみ）。
このため、`q`をやめて一覧をページングするだけの実装では、今度は一覧の
`item.get("metadata")`が常に`None`になり、依然として重複を検出できません
でした（同一ファイルが4件目以降も作られ続けた）。

`HttpElabftwClient.find_duplicate`は最終的に、`limit`/`offset`
（デフォルト15/0）でTemplate一覧を全件ページングしてid一覧を取得し、
各idについて個別取得(`GET /experiments_templates/{id}`)で実際の
`metadata.maiml_source`を1件ずつ照合する方式にしました（該当Templateが
多いと個別取得の回数分だけ余分なリクエストが増えますが、一覧APIが
そもそもmetadataを含まない以上、これが唯一の確実な方法です）。

## 方針

- 1 method = 1 eLabFTW Experiment Template
- PNMLを勝手に線形化しない
- API書込み前にTemplatePlan全体を検証する
- `source_document_uuid + source_method_uuid`で同一性を判定する
- 元MaiMLと逆変換用metadataを保持する
- 既存Templateを上書きしない
- 部分作成時は今回作成したリソースのみ補償削除する

## 開発

```bash
python -m pip install -e .
PYTHONPATH=src python -m unittest discover -s tests -v
```
