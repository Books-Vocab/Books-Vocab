# Tool friction

遇到 help 失準、命令輸出不自解、入口漂移、權限誤判或會誘導人工繞路時：

1. 保存最小重現命令、環境、exit status 與完整輸出；
2. 判斷是 source bug、工具 bug、文件 bug、權限／外部狀態，還是單純使用錯誤；
3. 能安全修的工具與 docs 先修，再回到原本的 direct assignment／Issue／PR；
4. 不能安全自決的成本、策略、生產與帳號動作，依是否需要長期追蹤建立 GitHub Issue 或留 PR comment，並停在可回滾邊界。

工具修正仍走一般 GitHub flow：branch → PR → Actions → review → merge。不要用 receipt、臨時檔或另一個 repo ledger 藏住摩擦。
