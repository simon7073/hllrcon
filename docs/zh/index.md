# `hllrcon` - Hell Let Loose RCON

**hllrcon** 是 [Hell Let Loose](https://www.hellletloose.com/game/hll) 游戏 RCON 协议的异步 Python 实现。它允许你以编程方式与 HLL 服务器交互，支持现代 Python 异步特性与健壮的错误处理。

## 功能特性

- 完整的 async/await 支持
- 命令执行与响应解析
- 内置官方地图、阵营、武器、载具等数据集合
- 为同步应用提供替代接口
- 类型完整且经过充分测试

## 安装

```sh
pip install hllrcon
```

## 快速开始

```py
import asyncio
from hllrcon import Rcon, Layer


async def main():
    # 初始化客户端
    rcon = Rcon(
        host="127.0.0.1",
        port=12345,
        password="your_rcon_password",
    )

    # 发送命令，客户端会自动（重新）连接
    await rcon.broadcast("Hello, HLL!")
    await rcon.change_map(Layer.STALINGRAD_WARFARE_DAY)
    players = await rcon.get_players()

    # 断开连接
    rcon.disconnect()

    # 或者使用上下文管理器，无需手动断开
    async with rcon.connect():
        assert rcon.is_connected() is True
        await rcon.broadcast("Hello, HLL!")


if __name__ == "__main__":
    asyncio.run(main())
```

对于同步应用，可使用 `SyncRcon`：

```py
from hllrcon.sync import SyncRcon

rcon = SyncRcon(
    host="127.0.0.1",
    port=12345,
    password="your_rcon_password",
)

with rcon.connect():
    rcon.broadcast("Hello, HLL!")
```

## 高级示例

```py
from hllrcon import Weapon

# 根据 ID 查找武器
weapon_id = "COAXIAL M1919 [Stuart M5A1]"
weapon = Weapon.by_id(weapon_id)

# 输出攻击者必须所在的载具座位（如果有）
if weapon.vehicle:
    for seat in weapon.vehicle.seats:
        if weapon in seat.weapons:
            print("该武器属于", seat.type.name, "座位")
            break
```

```py
from hllrcon import Rcon, Map, Team

# 获取 AA Network 占领区（SMDM，第 3 据点，第 2 占领区）
sector = Layer.STMARIEDUMONT_WARFARE_DAY.sectors[2]
capture_zone = sector.capture_zones[1]
assert capture_zone.strongpoint.name == "AA Network"

# 获取当前在线玩家
rcon = Rcon(...)
players = await rcon.get_players()

# 计算双方对占领区的占领强度
strength = {Team.ALLIES: 0, Team.AXIS: 0}
for player in players.players:
    if player.faction is None:
        continue

    if player.world_position == (0.0, 0.0, 0.0):
        # 玩家已阵亡。注意：不包括正在流血的玩家
        continue

    # 在据点内获得 3 点强度
    if capture_zone.strongpoint.is_inside(player.world_position):
        strength[player.faction.team] += 3

    # 仅在占领区内获得 1 点强度
    elif capture_zone.is_inside(player.world_position):
        strength[player.faction.team] += 1

# 输出结果
print("盟军占领权重:", strength[Team.ALLIES])
print("轴心国占领权重:", strength[Team.AXIS])
```

## 版本说明

Hell Let Loose（以下简称"游戏"）是一款不断演进的在线游戏，游戏更新可能会以不兼容的方式改变其 RCON 接口。这会影响所有依赖它的工具和库，包括本库以及任何使用本库的软件。

`hllrcon` 的每个发行版仅保证与发布时游戏的最新版本兼容。有关具体兼容的游戏版本，请参阅对应版本的发行说明。

本项目使用类似 [Pragmatic Versioning](https://pragver.github.io/spec/) 原则的四级版本号（即 `GRADE`.`MAJOR`.`MINOR`.`PATCH`），但各组件的定义和保证有所不同：

- **`GRADE`** — 保留给结构性变更。通常仅在 [Hell Let Loose: Vietnam](https://www.hellletloose.com/game/hll-vietnam) 发布时增加。
- **`MAJOR`** — 不兼容的 API 变更时递增。
- **`MINOR`** — 放弃对先前支持的游戏版本的支持时递增。
- **`PATCH`** — 向后兼容的修复或小功能时递增。

在指定 `hllrcon` 作为依赖时，建议固定 `MINOR` 版本，但不要固定 `PATCH` 版本。`MINOR` 版本仍然是不向后兼容的，因为它要求游戏服务器必须更新。`MINOR` 版本可能依赖于即将发布、尚未正式发布的游戏版本。

## 许可证

本项目基于 MIT 许可证开源。详见 [`LICENSE`](https://github.com/simon7073/hllrcon/blob/master/LICENSE)。
