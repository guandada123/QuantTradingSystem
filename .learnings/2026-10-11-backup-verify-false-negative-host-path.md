# ✅已升级(2026-10-11)→R22 —— 备份校验把**宿主路径**塞进容器 → 校验恒失败（假失败掩盖真失败）

**日期**：2026-10-11（全项目审计；首次补跑每日备份时暴露）
**等级**：P1（备份系统可信度；且「恒红」会让真失败淹没在噪音里）
**类型**：false-negative / environment-boundary
**状态**：已修复（改为 `docker cp` 进容器再校验；新建每日备份自动化）

---

## 1. 现象

`scripts/backup.sh` 的 `verify_backup()`：

```bash
# 修复前（错误）
docker exec -i "$CONTAINER_NAME" pg_restore --list "$backup_file"
```

`$backup_file` 是**宿主路径**（`/Users/guan/.../backups/daily/xxx.dump`），
容器内根本看不到宿主文件系统 → 命令必然非 0 → **每次备份都报 “integrity FAILED”**。

## 2. 证据（实测）

- 同一 dump 用 `docker cp` 拷进容器后校验：`Archive created 09:17:30 / TOC Entries: 277 /
  TABLE DATA: 43` → **dump 完全有效**。
- 修复后重跑：`Backup integrity verified: ...`，rc=0。

## 3. 危害

- **假失败**会让运维把「备份失败」当常态 → 告警疲劳 → 真失败没人看；
  极端情况下有人会因此**关掉备份**。
- 与「上游失败→下游静默」是**对偶形态**：一个是失败被吞，一个是成功被误报为失败，
  共同点都是**告警信号与事实脱钩**。

## 4. 修法与判据

- 修法：`docker cp` 进容器 → `pg_restore --list` → 清理临时文件（幂等）。
- 判据（写进备份自动化的 prompt）：**「备份文件存在 ≠ 备份有效」**，
  必须看到 `Backup integrity verified` 一行才算成功；只看文件大小/退出码都不算。
- 配套：新建每日自动化（daily + 周日 weekly + 每月 1 日 monthly，02:20），
  失败**必须**推飞书告警（禁止静默）。
- 备份落点：`/Volumes/ZHITAI`（外置 SSD），与 Docker 内部虚拟磁盘**异设备** —— 这是
  「备份必须与源数据异设备」最低要求的落地检查项。

## 5. 推广

- 任何「宿主 ↔ 容器」协作的脚本都要先问：**这个路径在对面看得见吗？**
  （同族：`docker logs --since 在本机不可信`、`宿主机端口可能不是容器端口`）
- 备份三件套：**能生成 + 能校验 + 能恢复演练**。本脚本有 `restore` 子命令但
  **从未演练过** —— 恢复演练列为后续待办。
