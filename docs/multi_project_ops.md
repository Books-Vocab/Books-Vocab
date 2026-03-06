# KG API 多專案共機操作說明（安全包裝）

## 為何新增
同一台主機有多個專案時，直接操作 `devops.sh` 風險較高。
此文件搭配 `ops/devops_kg_safe.sh`，以白名單模式降低誤操作。

## 建議日常操作
```bash
./ops/devops_kg_safe.sh preflight
./ops/devops_kg_safe.sh deploy
./ops/devops_kg_safe.sh status
./ops/devops_kg_safe.sh logs 120
```

## 白名單命令
- `deploy`
- `restart`
- `status`
- `logs`
- `backup`
- `env-check`
- `migrate`
- `users`
- `user-info`
- `run`（含危險字串過濾）

## 預設封鎖
- `setup`
- `push-env`
- `delete-user`
- `ssh`
- 任意破壞性 `run` 指令

## 原則
1. 先 preflight，再操作。
2. 若真的要用被封鎖命令，必須人工審核後直接執行 `devops.sh`。
3. 發生事故後要更新根目錄背景文檔與本檔。
