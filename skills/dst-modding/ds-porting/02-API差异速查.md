# 02 API 差异速查

表中结论来自已完成的移植模组和对单机源码的核对。遇到表里没有的 API，先在单机四份源码里搜索它的定义，再决定写法。

## 1. 全局与网络层

| 联机版 | 单机版 | 说明 |
|---|---|---|
| `TheWorld` | `GetWorld()` | 世界实例 |
| `ThePlayer` / `AllPlayers` | `GetPlayer()` | 只有本地玩家 |
| `TheNet` / RPC / `ismastersim` | 删除 | 全部本地执行 |
| `player_classified` / `net_*` / Replica | 本地组件字段 + 事件 | 技能 XP、形态值等 |
| `TheInventory`（皮肤） | 删除 | 单机无皮肤系统 |
| `TheWorld.state.isfullmoon` 等 | `GetClock()` 的方法 | 月相、昼夜用 `GetClock()` |
| `entity:SetPristine()` | 空函数垫片 | |
| `AnimState:AnimateWhilePaused` | 存在才调用 | 技能树界面常需要 |
| `FrameEvent(n, fn)` | `TimeEvent(n * FRAMES, fn)` | SG 帧事件 |
| `inst:HasAnyTag` / `HasOneOfTags` | 自行实现 | |
| `inst:AddComponent()` 返回值 | 单机不返回组件 | 用 `inst.components.<名字>` 取 |
| `Inventory:ForEachItem` | 自行实现（含哈姆雷特 overflow 容器） | |
| `MakeHauntableLaunch` 等闹鬼 | 空实现 | 单机无闹鬼 |
| `GLOBAL.XXX` 直接读 | 先确认字段存在 | 避免 `__STRICT` 报错，用 `rawget(_G, "XXX")` |

## 2. 战斗、阵营、伤害

| 联机版 | 单机版 |
|---|---|
| `damagetypebonus` / `damagetyperesist` | 钩 `Combat:GetAttacked`，按标签映射 |
| 平面伤害 / 平面防御 | 单机没有：改为普通伤害加成、固定减伤或省略 |
| `shadow_aligned` / `lunar_aligned` | 暗影映射 `shadow`、`shadowcreature`、`nightmarecreature`；单机几乎没有月亮阵营怪 |
| `shadow_item` 标签 | 单机暗夜剑、夜甲等按 prefab 名识别 |
| `customdamagemultfn` | 钩 `Combat:CalcDamage` |
| 世界事件 `entity_droploot` | 常不存在：用 `entity_death` + `combat.lastattacker` |
| 死亡事件 `data.afflicter` | 常为空：用 `combat.lastattacker` |
| `FindEntities` 必需标签 `_combat` | 单机标签是 `hascombatcomponent`，或不加必需标签、改为组件判断 |
| `Combat:TargetIs(x)` | Base 没有：比较 `combat.target == x` |
| `Combat:TryAttack` | 单机会读 `inst.sg`：无 SG 的炮塔用周期任务调 `StartAttack()` + `DoAttack(target)` |
| `AddDamageModifier(key, 2)` | SW/Hamlet 的修正值是相对 1 的加数：×2 要传 `+1` |
| `AddBurnRateModifier` | 同上，传 `mult - 1`；Base/RoG 用 `hunger:SetRate`，不要写 `hunger.burnrate`（被腰带等装备占用） |

阵营 hook 模板：在 `Combat:GetAttacked` 里，攻击方带 `player_<阵营>_aligned` 时对敌对阵营增伤；防守方带该标签时对同阵营来源减伤；来源同时检查 attacker 和 weapon。

## 3. 各 DLC 之间的分叉

| 项目 | Base / RoG | SW / Hamlet | 处理 |
|---|---|---|---|
| `Recipe` 构造函数 | 无 `game_type` 参数 | 第 5 个参数是 `game_type` | 见 [03](03-技能树配方与界面.md) 第 4 节探测 |
| 移速倍率 `walkspeedmult` | 乘算（手杖 1.15 → ×1.15） | 加算（+0.15） | 按 `CANE_SPEED_MULT` 探测 |
| 装备减速通道 | `Equippable:GetWalkSpeedMult` | `locomotor.speed_modifiers_mult["equipslot_<槽>"]` | 两条都要处理 |
| 世界碰撞掩码 | `COLLISION.WORLD` | 哈姆雷特没有 `COLLISION.WORLD` | 用 `GetWorldCollision()`，按存在性加 `COLLISION.WAVES` / `INTWALL` |
| 准星 `SetValidateFn` / `NeedsValidation` | 没有 | 仅哈姆雷特有 | 存在性检查 |
| `ComplexProjectile` | 可能没有 `SetGravity`；需补 `yOffset`、`horizontalSpeed` | | 落地后移除 `complexprojectile`，否则 SW/Hamlet 的 `DoAttack` 会把它当投掷武器 |
| 投掷物 | `complexprojectile` + 自定义 TOSS | 优先 `throwable` | |
| 武器伤害读取 | `weapon.damage` | `Weapon:GetDamage()` | |
| 弹药/投射物时机 | | 投射物可能在选定弹药前就生成 | 发射前先确定弹药 |
| 船 `driver`、`keeponland`、`poisonable` | 无 | 有 | 形态变化、跳跃、死亡要处理；变身形态期间抑制 `keeponland` |
| 湿度 `moisture` | Base 无物品湿度 | 有 | 防水钩 `Inventory:GetWaterproofness` |
| 室内 `interiorspawner` | 无 | 哈姆雷特 | 远程传送、地图跳跃要禁止或保持原位 |
| `RegisterInventoryItemAtlas` | 本体有，RoG（DLC0001）没有 | 有 | 存在性检查 |
| 原版物品栏图标图集 | `inventoryimages` | 哈姆雷特部分挪到 `inventoryimages_2` | 按实际图集查找 |
| 额外语音事件 | | SW/Hamlet 会请求 `sinking_death`、`gasmask_hurt`、`gasmask_talk` | 重映射到本角色已有语音 |

## 4. 单机没有的系统

| 联机版 | 单机替代（案例） |
|---|---|
| 鬼魂、作祟复活、他人复活 | 死亡时自动触发复活（旺达第二次机会表）；接入 `resurrector` 流程（机器人备份躯体） |
| 分片、洞穴跨服 | 记录存档模式（RoG/SW/火山/哈姆雷特/洞穴号）和哈姆雷特房间名，跨世界按航海门的方式存档切换（旺达） |
| Boss 忠诚门槛（织影者、天体英雄） | 技能点门槛（常用 12 点）+ 两阵营互斥 |
| 法术轮盘 spellbook / AOE 准星 | 自建轮盘 Screen（温蒂）、切换键 + 光标施法键（麦斯威尔）、物品栏左键施法右键切换（薇洛） |
| 角色专属制作筛选 | 角色专属制作栏，与薇克巴顿书本栏同一机制（旺达） |
| `pethealthbar` | 自建徽章（温蒂） |
| VFX 粒子 | 单机不支持，省略或换动画特效 |
| `rooted` 组件 | 移速归零 + 障碍碰撞（麦斯威尔石柱） |
| hauntable 恐慌 | 暂停 AI、丢失目标、外逃、减速 |
| `tackler` | 自定义动作 + SG（伍迪麋鹿冲撞） |
| `channelcastable` 持续施法 | 物品栏动作瞬时生效（薇洛） |
| 单物品腐烂倍率 | 给容器加 `fridge` 标签（温蒂骨灰罐） |
| 联机版独有物品 / 材料 | 用单机已有材料替代，或省略配方（威尔逊彩虹宝石、沃姆伍德亮茄材料） |

## 5. 引擎语义差异（同名 API 行为不同）

以下都是实际踩过的坑，写钩子或事件回调前必须核对。

### 动作与物品栏

- **`Action()` 的距离是第 5 个位置参数**：`Action(data, priority, instant, rmb, distance)`。联机版写在数据表里的 `distance` 字段单机不读，动作距离会退回默认值约 1.2。
- **物品栏右键只执行 `actions[1]`**，且 `UseItemFromInvTile` 请求物品栏动作时不带 `right` 标志：施法类动作要放在普通物品栏动作里；多个指令要做成轮盘或切换动作。
- `Lighter:Light(target)` 单机只有一个参数，doer 从物品栏主人或 `GetPlayer()` 取。
- `TakeFuelItem` / `ADDFUEL` 不传 doer。
- `Burnable:Ignite(immediate)` 单机只有一个参数，不能传 source。
- `PropagateFire` 阻止蔓延 → `propagator:StopSpreading` 并拦截 `StartSpreading`。
- `builder_tag` 单机不原生支持 → 钩 `Builder:KnowsRecipe` / `CanBuild`。
- 哈姆雷特 `ACTIONS.PICKUP` 会处理商店货架（`shelfer`）上的商品：任何自动拾取逻辑都要跳过 `shelfer`。

### 组件事件时序

- **`Pickable:Pick`**：只有采摘者有 `inventory` 时才生成产物；`picksomething` 事件在 `GiveItem` 和 `canbepicked = false` **之前**推送。在事件回调里采摘别的植物、读写目标状态时注意此时目标仍是可采状态。没有 `inventory` 的随从调用 `Pick` 只会走植物自身的记录（再生、`onpickedfn`），不会产出物品。
- **`Workable:WorkedBy`**：先扣 `workleft`，再推送 `working` 事件，最后才判断完成。在 `working` 回调里再对同一目标 `WorkedBy` 会嵌套执行，目标的完成回调执行两次（石头掉双倍并重复移除）。协助类逻辑用 `DoTaskInTime(0, ...)` 延后一帧，并重新检查目标有效、`workleft > 0`。
- **`Trader:AcceptGift`**：接收者没有 `inventory` 时，礼物在 `onaccept` 之前就被移除；`onaccept` 里再调用 `Eater:Eat` 会对已移除实体再走一次删除流程。
- **`Rideable` 死亡监听**会调用 `SetSaddle(nil)`，按真实鞍实体处理（`ReturnToScene`、`FlingItem`）。用占位表做鞍时要拦截这条路径，并给占位鞍补 `GetBonusSpeedMult`、`GetBonusDamage`（骑乘时每帧调用）。
- **死亡流程先掉落物品栏再判断复活**：依赖死亡时持有物的技能要在 `DropEverything` 前暂存物品。
- `wormhole.lua` 不检查 `nowormholesanityloss`：需要钩虫洞传送，只抵消那一次理智扣除。
- `GetDistanceSqToPoint` 在旧版单机接收一个 `Vector3`，不是三个数。
- `SoundEmitter` 停止命名声音用 `KillSound`，没有 `StopSound`。
- 单机事件监听器收到的参数和联机版闭包假设可能不同：回调里显式捕获真实实例。
- `EntityScript:DoTaskInTime(time, fn, ...)` 回调参数是 `(inst, ...)`。

### 状态图与表现

- **受击打断**：单机受击处理忽略 `nointerrupt` 标签，不能被打断的状态改用 `not_hit_stunned`（旺达回溯、跳门、复活）。
- **挂在玩家身上的特效**：单机不把父实体朝向传给子实体，特效要每帧复制玩家朝向，否则朝向不同时左右反转。
- 联机版独有的动画（`useitem_pre/pst`、`death_reverse` 等）在单机 bank 里不存在：用实际 bank 列表核对，缺的从联机版导出或换现有动画。
- 动画事件缺失时，在 `timeout` / `onupdate` 里补逻辑兜底。
- 单机的 `SGwilson` 某些动作只认特定物品标签（如 `PLAY` 只认笛子和号角）：用 `AddStategraphPostInit` 包装路由。
- 地面标记类特效要设置排序高于地皮，否则画在地面下面看不见。
- `customidleanim` 接入 `funnyidle` 时注意温度、饥饿、理智、中毒（哈姆雷特 `poisonable`）条件。

### 随从与 AI

- 移植联机版的自动拾取 / 采集 AI 时，**完整照搬联机版过滤条件**（`FindPickupableItem_filter`、`PICKUP_CANT_TAGS`）：跳过玩家当前缓冲动作的目标（`leader:GetBufferedAction().target`）、装备/武器/工具/护甲、容器、陷阱和诱饵、会动的生物、着火物品、`INLIMBO`/`NOCLICK`/`irreplaceable`/光源/暖石/建筑等标签；单机额外跳过哈姆雷特货架。缺了这些，随从会抢走玩家正要捡的东西。
- `FindEntities` 不要无标签全量扫描：至少带上排除标签。

### 存档与世界身份

- 跨洞穴、跨世界的进度用 `SaveGameIndex` 区分：`GetCurrentMode`、`GetSlotWorld`、`GetCurrentCaveNum`、`GetCurrentCaveLevel`（洞穴号是第二个参数，易写反）。
- 哈姆雷特同一时间只加载一个室内：跨世界存档前先离开当前房间（同原版 `TravelBetweenWorlds`）；室内内的传送不能当成「出到室外」处理，否则掉进虚空黑屏。
- 组件尽早 `AddComponent`，`OnLoad` 兼容旧字段名，读档后延迟一帧再应用技能效果。

## 6. 常用兼容垫片

按需裁剪，放在带模组前缀的文件里（见 [01](01-流程与模组结构.md) 第 3 节命名冲突）：

- `Inventory:ForEachItem` / `ForEachItemSlot`（含 overflow）
- `Container:ForEachItem` / `DropItemAt`
- `EntityScript:HasOneOfTags` / `HasAnyTag`
- `Equippable:IsRestricted` + 动作收集拦截
- `Follower:KeepLeaderOnAttacked` / `LoseLeaderOnAttacked`
- `FiniteUses:SetDoesNotStartFull` + OnSave
- `FrameEvent`、`MakeHauntableLaunch`、`Entity.SetPristine`、`AnimState.AnimateWhilePaused`
- `PI2` / `TWOPI`、`Combat:TargetIs`、`table.removearrayvalue`

每个垫片先判断目标是否已存在（`if X == nil then`），不覆盖单机或其他模组已有的实现。
