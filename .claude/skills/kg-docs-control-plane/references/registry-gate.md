# Registry gate

只有執行 `./ops/docs_lint.sh --registry` 或新增／修改 generated entry 時載入本 reference。

- 每個 generated entry 必須指定 generator 與 check。
- check 必須明確指名自己驗證的產物 path，並以 exit status 表示是否等值。
- registry schema、path existence、generator 與 check 任一失效都回 ERROR。
- historical material 不屬於 generated gate；需要當下狀態時讀 active SoT。
