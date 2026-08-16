# Registry Gate

只有執行 `./ops/docs_lint.sh --registry`、新增／修改 `kind: generated` entry，或需要診斷 generated
check 時載入；一般 docs impact、surface sync 與 agent-facing audit 不預載。

`--registry` 會執行每筆 `kind: generated` 的 `check:` 命令。generated entry 缺少 `check:` 是 ERROR；
check 與產物不一致時，輸出具名 entry 與重生命令。registry validation 不因 lint mode 改變，所有模式都會
先驗 schema。

目前 registry 的 generated entry 數量與產物是否已移出版控是 live state，不得寫死在 kernel 或其他 skill；
需要當下數字時直接執行：

```bash
./ops/docs_lint.sh --registry
```

generated contract 的合成失敗路徑由 `ops/tests/test_docs_lint_generated_check.sh` 守護；不要把 archive、
snapshot 或 backlog coverage debt 當成 generated gate failure。
