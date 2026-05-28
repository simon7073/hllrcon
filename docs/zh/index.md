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

## 版本说明

本项目的版本号采用 `GRADE.MAJOR.MINOR.PATCH` 四级格式：

- **`GRADE`** — 结构性变更
- **`MAJOR`** — 不兼容的 API 变更
- **`MINOR`** — 放弃对旧游戏版本的支持
- **`PATCH`** — 向后兼容的修复/小功能

## 许可证

本项目基于 MIT 许可证开源。详见 [LICENSE](/LICENSE)。
