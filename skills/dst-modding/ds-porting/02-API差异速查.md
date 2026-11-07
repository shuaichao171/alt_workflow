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

三点时序/参数语义（威尔逊 2026-10-31，源码：对照单机四份源码后修正）：

- **增伤**对齐 DST 的 `damagetypebonus`（在攻击方 `CalcDamage` 里乘算，属护甲**前**），因此在 `Combat:GetAttacked` 里乘算正确。
- **抗性**对齐 DST 的 `damagetyperesist`：DST 先 `inventory:ApplyDamage`（护甲吸收）再乘 `damagetyperesist`。写进 `GetAttacked` 会对护甲前伤害乘算，与护甲的固定吸收叠乘（100 伤害 + 80 吸收：护甲前只吃 10，护甲后吃 18），比 DST 强得多。正确做法是钩 `Inventory:ApplyDamage` 的返回值（woodie 案例同此法）。
- **单机四份 `Combat` 调 `Inventory:ApplyDamage(damage, attacker)` 都不传 weapon**（Base/DLC0001/DLC0002/DLC0003 全部如此），护甲后的抗性要识别“武器提供的阵营”就必须在 `GetAttacked` 里把 weapon 暂存到目标（`inst._xxx_incoming_weapon`），`ApplyDamage` 里用 `weapon or inst._xxx_incoming_weapon`。

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
| `Builder:KnowsRecipe` | 直接按等级 / `recipes` 判断 | `jellybrainhat or KnowsRecipeWithoutJellyBrainHat(recname)`，后者还决定这次建造是否扣果冻脑帽耐久 | 专属配方两个方法都包装（沃特 2026-11-07，源码） |
| `fishmeat` 标签 | 无 | 打在所有海鲜上（蛙腿、贻贝、帽贝、鲸脂、鲨鱼鳍……） | 对应 DST `fishmeat` 的判断按 prefab 名单（沃特 2026-11-07，源码） |

## 4. 单机没有的系统

| 联机版 | 单机替代（案例） |
|---|---|
| 鬼魂、作祟复活、他人复活 | 死亡时自动触发复活（旺达第二次机会表）；接入 `resurrector` 流程（机器人备份躯体） |
| 分片、洞穴跨服 | 记录存档模式（RoG/SW/火山/哈姆雷特/洞穴号）和哈姆雷特房间名，跨世界按航海门的方式存档切换（旺达） |
| Boss 忠诚门槛（织影者、天体英雄） | 技能点门槛（常用 12 点）+ 两阵营互斥 |
| 法术轮盘 spellbook / AOE 准星 | 自建轮盘 Screen + 移植 reticuleaoe 准星（温蒂、麦斯威尔）、切换键 + 光标施法键（麦斯威尔辅助）、物品栏左键施法右键切换（薇洛） |
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
- `builder_tag` 单机不原生支持 → 钩 `Builder:KnowsRecipe` / `CanBuild` / `DoBuild`。只钩这些挡不住制作栏的灰色提示，等级还要加 `LOST` 或包装提示函数（见 [03](03-技能树配方与界面.md) 4.4）。
- 哈姆雷特 `ACTIONS.PICKUP` 会处理商店货架（`shelfer`）上的商品：任何自动拾取逻辑都要跳过 `shelfer`。

### 组件事件时序

- **`Pickable:Pick`**：只有采摘者有 `inventory` 时才生成产物；`picksomething` 事件在 `GiveItem` 和 `canbepicked = false` **之前**推送。在事件回调里采摘别的植物、读写目标状态时注意此时目标仍是可采状态。没有 `inventory` 的随从调用 `Pick` 只会走植物自身的记录（再生、`onpickedfn`），不会产出物品。
- **`Workable:WorkedBy`**：先扣 `workleft`，再推送 `working` 事件，最后才判断完成。在 `working` 回调里再对同一目标 `WorkedBy` 会嵌套执行，目标的完成回调执行两次（石头掉双倍并重复移除）。协助类逻辑用 `DoTaskInTime(0, ...)` 延后一帧，并重新检查目标有效、`workleft > 0`。
- **`Trader:AcceptGift`**：接收者没有 `inventory` 时，礼物在 `onaccept` 之前就被移除；`onaccept` 里再调用 `Eater:Eat` 会对已移除实体再走一次删除流程。
- **`Rideable` 死亡监听**会调用 `SetSaddle(nil)`，按真实鞍实体处理（`ReturnToScene`、`FlingItem`）。用占位表做鞍时要拦截这条路径，并给占位鞍补 `GetBonusSpeedMult`、`GetBonusDamage`（骑乘时每帧调用）。
- **死亡流程先掉落物品栏再判断复活**：依赖死亡时持有物的技能要在 `DropEverything` 前暂存物品。
- **`Hunger:DoDelta` 对无敌实体直接返回**：四份源码（DLC0001 用本体那份）都先判断 `health.invincible`（以及 `is_teleporting`），除非第 3 个参数 `ignore_invincible` 为真。为了能被骑乘而把坐骑/宠物设成 `SetInvincible(true)` 后，进食和随时间消耗都不再改变饥饿值：小沃比喂多少都不长大。只给这个实体的 hunger 包一层 `DoDelta`，固定传 `ignore_invincible = true`（沃尔特 2026-11-05，源码）。
- `wormhole.lua` 不检查 `nowormholesanityloss`：需要钩虫洞传送，只抵消那一次理智扣除。
- `GetDistanceSqToPoint` 在旧版单机接收一个 `Vector3`，不是三个数。
- `SoundEmitter` 停止命名声音用 `KillSound`，没有 `StopSound`。
- **`GetString(character, key)` 的第一个参数是角色名字符串**：四份单机源码都先 `string.upper(character)`，传实体（DST 写法 `GetString(inst, ...)`）直接报错；传 `inst.prefab`（沃特 2026-10-31，源码）。
- **地面加速只认 ROAD/COBBLEROAD**：`LocoMotor:UpdateGroundSpeedMultiplier` 每 0.5 秒先把 `groundspeedmultiplier` 重置为 1 再判断蛛网、道路、洪水。DST 的 `SetFasterOnGroundTile` 要包装这个方法、只在结果为 1 时升档，不要另开轮询去写字段（会互相覆盖并无视蛛网/洪水减速）（沃特 2026-10-31，源码）。
- **潮湿滑落只看物品 `notslippery` 标签**：单机 `player_common` 的 `OnWork`/攻击回调里，手持物没有 `notslippery` 就可能滑落；DST 的 `stronggrip` 标签单机不读，改为装备时给手持物临时加 `notslippery`、卸下时移除（沃特 2026-10-31，源码）。
- **`Health:DoDelta` 没有 afflicter 参数**：DST `deltamodifierfn` 靠 `afflicter ~= nil` 只处理攻击伤害；单机要在 `Combat:GetAttacked` 期间给目标置标志，否则火焰、饥饿等伤害也会被当成战斗伤害（沃特 2026-10-31，源码）。
- **素食**：Base `SetVegetarian()` 只设 `foodprefs = {VEGGIE, ROUGHAGE}`；RoG+ `SetVegetarian()` 不传 `human` 时 `ablefoods = {VEGGIE}`，种子、GENERIC 都吃不了。对齐 DST `FOODGROUP.VEGETARIAN` 要同时设 `foodprefs` 和 `ablefoods`（单机没有 BERRY/GOODIES 类型）（沃特 2026-10-31，源码）。
- 单机没有 `foodaffinity`、`itemaffinity`、`preserver` 组件：饱食加成钩 `Edible:GetHunger(eater)`（四份签名一致；SW/Hamlet 另有 `eater.gethungermultfn`，两者别同时用）；`perishable` 不查询持有者的 `preserver`（沃特 2026-10-31，源码）。
- **`Reader:Read` 总是施法**：DST 沃特的 `aspiring_bookworm` 只翻阅（说 `ANNOUNCE_READ_BOOK` 台词、扣 1 次耐久、加减 `peruse_sanity`）。单机要包装 `Reader.Read` 按标志改走翻阅（沃特 2026-11-07，源码）。
- 单机事件监听器收到的参数和联机版闭包假设可能不同：回调里显式捕获真实实例。
- **DST 法术轮盘（spellbook + aoetargeting）的单机还原模式**（麦斯威尔 2026-11-07，实测）：开轮盘用 `Action({mount_enabled=true}, 2, true)` 即时动作（物品栏右键走组件 `CollectInventoryActions` 收集，DST 是 `USESPELLBOOK.pre_action_cb` 开轮盘）；施法用非即时动作 + `AddStategraphActionHandler("wilson", ActionHandler(动作, "book"))` 复用原版读书动画（58 帧处 `PerformBufferedAction`）；准星目标模式用移植的 `reticuleaoe` 美术（`ANIM_ORIENTATION.OnGroundFixed` 单机没有，用 `OnGround`；圆环旋转不变视觉等价）+ 每帧任务跟随 `TheInput:GetWorldPosition()` 并按施法距离钳制；左键施放、右键取消靠包装 `PlayerController.OnLeftClick/OnRightClick`（吞掉事件不落原逻辑，down 被吞后要吞对应 up）。
- **`FrontEnd:PushScreen` 的焦点链会触发旧屏 `OnLoseFocus`**（麦斯威尔 2026-11-07，源码+实测）：`OnBecomeActive → default_focus:SetFocus() → SetFocusFromChild → ClearFocus` 逐级上抛，旧活动屏（HUD）的 `OnLoseFocus` 在新屏入栈过程中就被调用（widget 级失焦，与 `ClearScreens` 里的前端栈 `OnLoseFocus` 是两回事）。在 HUD 失焦钩子里关闭刚推入的自建 Screen 会当场自毁。
- `EntityScript:DoTaskInTime(time, fn, ...)` 回调参数是 `(inst, ...)`。

### 状态图与表现

- **受击打断**：单机受击处理忽略 `nointerrupt` 标签，不能被打断的状态改用 `not_hit_stunned`（旺达回溯、跳门、复活）。
- **挂在玩家身上的特效**：单机不把父实体朝向传给子实体，特效要每帧复制玩家朝向，否则朝向不同时左右反转。
- 联机版独有的动画（`useitem_pre/pst`、`death_reverse` 等）在单机 bank 里不存在：用实际 bank 列表核对，缺的从联机版导出或换现有动画。
- **HUD 右上布局**：单机（含 SW/HAM）`controls.sidepanel` 在右缘 -80、`status` 在 (0,-110)，徽章 stomach(-40,20)/heart(40,20)/brain(0,-40)。两边这套坐标一致，DST SecondaryStatusDisplays 的 UpgradeModulesDisplay 坐标可直接照搬。**注意 `column1` 的符号**：`IsGameInstance(Instances.Player1)` 为真（所有普通对局）时是 **+60**，-60 只是分屏 2P 的镜像值。正确位置为 status 相对 (60,-133)，七格时 (60,-145)：心形图标正下方、电池本体贴右缘，电线伸出屏幕外，电路条向左展开（WX-78 2026-11-07 实机截图确认）。误用 -60 时电池落在脑图标左下，用户会指出与 DST 不符。早先“放徽章左侧”和“(-60,-133)”两种做法都已作废。
- **单机 Widget 无 `HookCallback`/`UnhookCallback`/`HasCallback`，AnimState 无 `GetBuild`**（DST-only）：widget 内“动画完成后做一次”用本地 helper 包 `inst:ListenForEvent("animover", fn)` + `RemoveEventCallback`，换钩前先解旧钩；GetBuild 用 prefab 已知 build 名常量替代（WX-78 托盘 widget 2026-11-06 实机三连崩后修复）。
- **`SetParent` + `FollowSymbol` 组合不等效 DST**：单机 SetParent 把子实体钉在父实体原点并破坏 Follower 的符号跟随（头顶特效实测画在脚部 dy≈0.5）；正确做法是 FollowSymbol 单独用（torch 火焰范式，引擎按 GUID 逐帧跟随），父实体清理用显式 `ListenForEvent("onremove")`。另：单机 Follower 只改渲染位置不改实体 transform——位置探针量 transform 会误判，判定以截图为准（WX-78 眩晕 FX 2026-11-06 实机+截图）。
- **locomote 事件无 `data.dir`**（DST 添加）：单机判“玩家想移动”用 `locomotor:WantsToMoveForward()`。测试模拟按住方向键必须每帧调 `RunInDirection(angle)`（PlayerController 同款），裸设 `wantstomoveforward` 会被 locomotor 自身更新清掉（WX-78 拆装循环状态 2026-11-06 实机）。
- **sg 事件是缓冲式**：`EntityScript:PushEvent` 经 `IsListeningForEvent` 门控后入 `sg.bufferedevents`（附 `data.state`=当前状态名），下一帧 `HandleEvents` 才派发；push 后同帧改组件状态会在派发时读到新值，先改后 push 则读旧值（WX-78 2026-11-06）。
- **vanilla bug：`EntityScript:PushBufferedAction` 的 dupe 检查比较不存在的 `inv_obj` 字段**（恒 nil）：失败动作未清时，同动作类型的下一次 push 会被当 dupe 静默丢弃；脚本连续推动作前先 `player.bufferedaction = nil`（WX-78 2026-11-06 实机：spin 芯片未插入根因）。
- **循环动画后 `PushAnimation`**：单机里当前动画是循环时，排队的动画会立刻接上，不会等这一圈播完（WX-78 旋转收招实测 `PPPPPPP`）。要“播完当前圈再收招”只能用短状态按剩余帧数等待后再 `PlayAnimation`。
- **攻击接近距离**：DST `LocoMotor` 对 ATTACK 用 `combat:LocomotorCanAttack`（攻击距离 + 目标半径）判到达；单机只认动作固定 `distance = 2`，`combat:SetRange` 加大的攻击距离只影响玩家大脑 `ChaseAndAttack` 的后续出手。需要远距离起手时给 ATTACK 的 `bufferedaction.distance` 放宽。
- **`Talker:IgnoreAll()`**：单机是一个布尔开关（无来源参数），`StopIgnoringAll` 会清掉别人设的忽略；只在 `talker.ignoring` 为假时接管并自己记账。
- 动画事件缺失时，在 `timeout` / `onupdate` 里补逻辑兑底。注意：纯 `onupdate` 状态在单机调度器下可能只被唤醒几次且 `dt=0`；逐帧效果优先用 timeline `TimeEvent`（薇格弗德 2026-10-29）。
- **单机 instant 动作绕过 SG**：`Action.instant=true` 时 `EntityScript:PushBufferedAction` 直接 `Do()`，不查 ActionHandler，动画状态不会进。要动画的动作用非 instant（无 target/pos 时会 `sg:StartAction` 走 ActionHandler）；必须 instant 的在 action fn 里显式 `GoToState`（薇格弗德 2026-10-29）。
- **状态图实例无 `HasState` / `states`**：单机 `StateGraphInstance` 上查状态要用 `inst.sg.sg.states[name] ~= nil`（模板的 `.sg` 字段才是状态表）；`GoToState` 对非法名字自会打印 INVALID STATE（薇格弗德 2026-10-29）。
- **玩家逐帧位移**：玩家实体的电机速度被 locomotor 每帧覆写，`Physics:SetMotorVel` 无效；冲锋/突进用 timeline 事件分帧 `Transform:SetPosition` 步进（薇格弗德 2026-10-29）。
- **需要碰撞的持续滑行**用 `Physics:SetMotorVelOverride(vx, 0, vz)`（局部坐标：先按 `Transform:GetRotation()` 把世界速度转过去），离开状态时 `ClearMotorVelOverride()` + `Stop()`；状态自循环（timeout 重入）时不要清，否则每圈顿一下。Hamlet `components/mapwrapper.lua` 就是这样推玩家的，比 `SetPosition` 步进少穿墙风险（机器人旋转电路 2026-11-06，源码；未实机）。
- **改写原版 ActionHandler / 全局事件**：`ActionHandler` 构造时把字符串目标包成函数，直接替换 `sg.actionhandlers[ACTIONS.X].deststate` 并在不接管时调用旧函数；全局事件在 `sg.events[name].fn`，同样可包装。deststate 返回 nil 时 `PushBufferedAction` 让动作 `Fail()`，不会瞬间执行。给包装打标记防止 `AddStategraphPostInit` 重复包装（机器人 2026-11-06，源码）。
- **单机 AnimState 没有 `SetFrame` / `GetCurrentAnimationFrame`**（四个 DLC 脚本都未出现，只有 `SetTime`、`GetCurrentAnimationLength`、`IsCurrentAnimation`）。DST 中途切帧的写法改成在时间轴边界切动画；循环动画的状态时长用实测帧数常量（机器人 2026-11-06，源码）。
- **动画按 bank 名跨 zip 合并**：把 DST 玩家动画（sing/parry/个性待机等）以同名 bank 导出成 mod zip 后，单机玩家 `PlayAnimation` 能直接命中，无需切 bank；角色专属符号用 `AddOverrideBuild`（薇格弗德 2026-10-29）。
- **modimport 顺序**：`AddStategraphActionHandler(ACTIONS.X, ...)` 在 `ACTIONS.X` 为 nil 时构造会让 SG 构造函数报 `table index is nil`——动作定义文件的 modimport 必须在 SG 文件之前（薇格弗德 2026-10-29）。
- **玩家的攻击循环在 `wilsonbrain` 里**：单机玩家有大脑，`ACTIONS.ATTACK` 只 `SetTarget`，由 `ChaseAndAttack(max_attacks = 1)` 反复 `TryAttack` 推 `doattack`，并在攻击距离内持续 `locomotor:Stop()`。这个节点只在收到 `onattackother` / `onmissother` 后计数结束。自建攻击状态如果某个分支不出手（弹弓没子弹只播空响），节点永不结束，角色一直空挥、移动也打断不了。不出手的分支要 `combat:SetTarget(nil)` 让节点失败退出，提示音和台词加冷却（按住 F 每帧都会重新发起攻击）（沃尔特 2026-11-05，源码）。
- **戴帽子的头部图层是 `HEAD_HAIR`，不是 `HEAD_HAT`**：四份 `hats.lua` 都是装备时 `Hide("HEAD")` + `Show("HEAD_HAIR")`，卸下时反过来，从不动 `HEAD_HAT`。而单机玩家动画里 `headbase_hat`（帽子下的整颗头，含皮肤和头发）就画在 `HEAD_HAT` 图层上。照搬 DST 帽子在卸下时 `Hide("HEAD_HAT")`，再换戴任何原版帽子，头就没了，只剩脸部五官悬空。自建帽子照单机写法只切换 `HEAD_HAIR`（沃尔特 2026-11-05，源码 + 解析 `player_basic.zip` 图层）。
- 单机的 `SGwilson` 某些动作只认特定物品标签（如 `PLAY` 只认笛子和号角）：用 `AddStategraphPostInit` 包装路由。
- 地面标记类特效要设置排序高于地皮，否则画在地面下面看不见。
- `customidleanim` 接入 `funnyidle` 时注意温度、饥饿、理智、中毒（哈姆雷特 `poisonable`）条件。

### 随从与 AI

- 移植联机版的自动拾取 / 采集 AI 时，**完整照搬联机版过滤条件**（`FindPickupableItem_filter`、`PICKUP_CANT_TAGS`）：跳过玩家当前缓冲动作的目标（`leader:GetBufferedAction().target`）、装备/武器/工具/护甲、容器、陷阱和诱饵、会动的生物、着火物品、`INLIMBO`/`NOCLICK`/`irreplaceable`/光源/暖石/建筑等标签；单机额外跳过哈姆雷特货架。缺了这些，随从会抢走玩家正要捡的东西。
- `FindEntities` 不要无标签全量扫描：至少带上排除标签。
- `FindEntity(inst, radius, fn, musttags, canttags, mustoneoftags)`：四份单机源码都支持第 6 个参数（沃特 2026-11-07，源码）。
- **单机 `merm` 不能雇佣**：没有 `trader`/`follower`，`mermbrain` 也没有 leader 节点。给 prefab 补组件，在 `AddBrainPostInit` 里往 `self.bt.root.children` 插节点并给新节点设 `.parent`；插在 `ShouldGoHome` 之前，否则随从会回家。`WhileNode` 实际是 `ParallelNode{ConditionNode(cond, name), node}`，按名字找位置要看 `children[1].name`。`behaviours/follow` 等文件在回调里 `require`（原脑不加载它们）。跟随时还要包装 `sleeper.sleeptestfn`，否则白天睡觉（沃特 2026-11-07，源码）。
- **生物对 `merm` 的态度和 DST 不同**：单机青蛙打任何有物品栏的目标（含沃特），DST 排除 `merm`；单机猪人只打 `monster`、谁喂都跟，DST 猪人敌视 `merm` 且不接受 `merm` 的雇佣。单机 `combat.targetfn` 是普通字段，猪人变身会再调 `SetRetargetFunction`，两处一起包装（沃特 2026-11-07，源码）。
- **随从的 `death` 回调里可能已经没有 leader**：单机 `PushEvent` 按监听实体 `pairs` 遍历，Leader 自己的 `death` 监听（`RemoveFollower`）可能先跑。死亡时要用 leader 的逻辑（暗影复苏之类），在 `Follower:SetLeader` 时把 leader 记到实例上，死亡后不清除（沃特 2026-11-07，实测）。
- `TUNING.RESEARCH_MACHINE_DIST` 单机只有 4：`Builder:EvaluateTechTrees` 每帧只找 4 格内的 `prototyper`（沃特 2026-11-07，实测）。

### 存档与世界身份

- 跨洞穴、跨世界的进度用 `SaveGameIndex` 区分：`GetCurrentMode`、`GetSlotWorld`、`GetCurrentCaveNum`、`GetCurrentCaveLevel`（洞穴号是第二个参数，易写反）。
- **进出洞穴、火山会带走全部随从**：`SaveIndex:GetSaveFollowers`（只在本体 `saveindex.lua`）对 `leader.followers` 里每个活着的随从 `GetPersistData` 后 `Remove()`，到新世界再生成并 `SetLeader`。如果宠物另外由角色自己的 `OnSave` / `OnLoad` 存档重建（`persists = false` 的跟宠常这么做），每走一次洞穴就多一只。包装 `GetSaveFollowers`：调用前把角色自己管理的宠物（和正在骑的坐骑）临时移出 `followers` 表、调用后放回；顺手合并之前已经多出来的副本（转移容器物品后移除）（沃尔特 2026-11-05，源码）。
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
