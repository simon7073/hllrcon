# `hllrcon` - Hell Let Loose RCON

**hllrcon** is an asynchronous Python implementation of the [Hell Let Loose](https://www.hellletloose.com/game/hll) RCON protocol.  
It allows you to interact with your HLL servers programmatically, supporting modern Python async features and robust error handling.

## Features

- Full async/await support
- Command execution and response parsing
- Collection of vanilla maps, factions, weapons, and more
- Alternative interfaces for synchronous applications
- Well-typed and tested

## Installation

```sh
pip install hllrcon
```

## Quick Start

```py
import asyncio
from hllrcon import Rcon, Layer


async def main():
    # Initialize client
    rcon = Rcon(
        host="127.0.0.1",
        port=12345,
        password="your_rcon_password",
    )

    # Send commands. The client will (re)connect for you.
    await rcon.broadcast("Hello, HLL!")
    await rcon.change_map(Layer.STALINGRAD_WARFARE_DAY)
    players = await rcon.get_players()

    # Close the connection
    rcon.disconnect()

    # Alternatively, use the context manager interface to avoid
    # having to manually disconnect.
    async with rcon.connect():
        assert rcon.is_connected() is True
        await rcon.broadcast("Hello, HLL!")


if __name__ == "__main__":
    asyncio.run(main())
```

For synchronous applications, a `SyncRcon` class is provided.

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

## Advanced Examples

```py
from hllrcon import Weapon

# Find a weapon by its ID
weapon_id = "COAXIAL M1919 [Stuart M5A1]"
weapon = Weapon.by_id(weapon_id)

# Print out whichever vehicle seat the attacker must have been in, if any
if weapon.vehicle:
    for seat in weapon.vehicle.seats:
        if weapon in seat.weapons:
            print("This weapon belongs to the", seat.type.name, "seat")
            break
```

```py
from hllrcon import Rcon, Map, Team

# Get the AA Network capture zone (SMDM, 3rd sector, 2nd capture zone)
sector = Layer.STMARIEDUMONT_WARFARE_DAY.sectors[2]
capture_zone = sector.capture_zones[1]
assert capture_zone.strongpoint.name == "AA Network"

# Get the current online players
rcon = Rcon(...)
players = await rcon.get_players()

# Calculate each team's capture strength towards the sector
strength = {Team.ALLIES: 0, Team.AXIS: 0}
for player in players.players:
    if player.faction is None:
        continue

    if player.world_position == (0.0, 0.0, 0.0):
        # Player is dead. Note: Does not exclude players bleeding out
        continue

    # Grant 3 strength if inside the strongpoint
    if capture_zone.strongpoint.is_inside(player.world_position):
        strength[player.faction.team] += 3

    # Only grant 1 strength if inside the capture zone
    elif capture_zone.is_inside(player.world_position):
        strength[player.faction.team] += 1

# Print out the results
print("Allied cap weight:", strength[Team.ALLIES])
print("Axis cap weight:", strength[Team.AXIS])
```

## Versioning

Hell Let Loose (referred to as "the game") is a constantly evolving game, and game updates might alter its RCON interfaces in ways that are not backward-compatible.
This affects any tools and libraries that depend on it, including this library and any software utilizing it.

Releases of `hllrcon` only guarantee compatibility with the latest version of the game at the time of release. See the release notes of a given version for more information on what version this is.

This project uses its own versioning system similar to [Pragmatic Versioning principles](https://pragver.github.io/spec/) (i.e. `GRADE`.`MAJOR`.`MINOR`.`PATCH`).
However, there are differences in the way each of the four components are defined and what they guarantee:

- **`GRADE`** - Reserved for structural changes. Likely to increase only with the release of [Hell Let Loose: Vietnam](https://www.hellletloose.com/game/hll-vietnam).
- **`MAJOR`** - Incremented when backward-incompatible changes are released.
- **`MINOR`** - Incremented when support for the previously supported game version is dropped.
- **`PATCH`** - Incremented when backward-compatible changes are released.

When specifying `hllrcon` as a dependency, it is recommended to pin the `MINOR` version but not the `PATCH` version. `MINOR` versions are still backwards-incompatible in that they require the game server to be updated. `MINOR` versions may depend on upcoming, unreleased game version.

## License

This project is licensed under the MIT License. See [`LICENSE`](https://github.com/simon7073/hllrcon/blob/master/LICENSE) for details.
