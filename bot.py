import os
import asyncio
import json
import time
from pathlib import Path

import discord
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
MUCHA_BOT_ID = int(os.getenv("MUCHA_BOT_ID", "0"))

# Start nowej rundy co 10 minut.
CHASE_INTERVAL = int(os.getenv("CHASE_INTERVAL", "600"))

# Jedna runda pościgu trwa 30 sekund.
CHASE_DURATION = int(os.getenv("CHASE_DURATION", "30"))

# Małe opóźnienie przy przeskakiwaniu między kanałami.
CHASE_DELAY = float(os.getenv("CHASE_DELAY", "0.5"))
STATUS_FILE = Path(
    os.getenv(
        "STATUS_FILE",
        str(Path(__file__).resolve().parent / "state" / "chaser_status.json"),
    )
)

status_data = {
    "online": False,
    "started_at": time.time(),
    "updated_at": time.time(),
    "interval_seconds": CHASE_INTERVAL,
    "duration_seconds": CHASE_DURATION,
    "delay_seconds": CHASE_DELAY,
    "bot": None,
    "guilds": {},
}


def update_status(guild: discord.Guild | None = None, **fields):
    if guild is None:
        status_data.update(fields)
    else:
        guild_state = status_data["guilds"].setdefault(
            str(guild.id),
            {"id": guild.id, "name": guild.name},
        )
        guild_state["name"] = guild.name
        guild_state.update(fields)

    status_data["updated_at"] = time.time()

    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATUS_FILE.with_suffix(STATUS_FILE.suffix + ".tmp")
        tmp.write_text(
            json.dumps(status_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(STATUS_FILE)
    except OSError as exc:
        print(f"Nie mogę zapisać statusu Chasera: {exc}")


intents = discord.Intents.default()
intents.voice_states = True

client = discord.Client(intents=intents)

active_chases: dict[int, bool] = {}
guild_locks: dict[int, asyncio.Lock] = {}


def get_lock(guild_id: int) -> asyncio.Lock:
    if guild_id not in guild_locks:
        guild_locks[guild_id] = asyncio.Lock()
    return guild_locks[guild_id]


def find_mucha_channel(guild: discord.Guild):
    for channel in [*guild.voice_channels, *guild.stage_channels]:
        if any(member.id == MUCHA_BOT_ID for member in channel.members):
            return channel
    return None


async def disconnect_from_voice(guild: discord.Guild):
    # Używamy tej samej blokady co connect/move, żeby końcowe
    # rozłączenie nie ścigało się z niedokończonym follow_mucha().
    async with get_lock(guild.id):
        voice = guild.voice_client

        if voice is not None:
            try:
                # Rozłączamy również wtedy, gdy VoiceClient jest jeszcze
                # w stanie connecting i is_connected() zwraca False.
                await voice.disconnect(force=True)
            except Exception as exc:
                print(
                    f"[{guild.name}] Błąd VoiceClient.disconnect: "
                    f"{type(exc).__name__}: {exc}"
                )

        # Fallback: jeśli Discord nadal pokazuje naszego bota na voice,
        # wymuszamy opuszczenie kanału bezpośrednio przez gateway.
        await asyncio.sleep(0.25)

        me = guild.me
        if me and me.voice and me.voice.channel is not None:
            try:
                print(
                    f"[{guild.name}] Fallback disconnect "
                    f"z kanału: {me.voice.channel.name}"
                )
                await guild.change_voice_state(channel=None)
            except Exception as exc:
                print(
                    f"[{guild.name}] Błąd fallback disconnect: "
                    f"{type(exc).__name__}: {exc}"
                )


async def follow_mucha(guild: discord.Guild):
    if not active_chases.get(guild.id, False):
        return

    async with get_lock(guild.id):
        if not active_chases.get(guild.id, False):
            return

        await asyncio.sleep(CHASE_DELAY)

        if not active_chases.get(guild.id, False):
            return

        target_channel = find_mucha_channel(guild)
        voice = guild.voice_client

        if target_channel is None:
            if voice and voice.is_connected():
                print(
                    f"[{guild.name}] Mucha wyszła z voice "
                    "-> czekam na nią w tej rundzie."
                )
                await voice.disconnect(force=True)
                update_status(
                    guild,
                    current_voice_channel=None,
                    current_voice_channel_id=None,
                    last_event="Mucha wyszła z voice",
                    last_event_at=time.time(),
                )
            return

        try:
            if voice and voice.is_connected():
                if voice.channel.id != target_channel.id:
                    print(
                        f"[{guild.name}] Mucha uciekła na: "
                        f"{target_channel.name} -> gonię!"
                    )
                    await voice.move_to(target_channel)
                    update_status(
                        guild,
                        current_voice_channel=target_channel.name,
                        current_voice_channel_id=target_channel.id,
                        last_event="podążam za Muchą",
                        last_event_at=time.time(),
                    )
            else:
                print(
                    f"[{guild.name}] Mucha jest na: "
                    f"{target_channel.name} -> wchodzę!"
                )
                await target_channel.connect(
                    timeout=20.0,
                    reconnect=True,
                    self_deaf=True,
                )
                update_status(
                    guild,
                    current_voice_channel=target_channel.name,
                    current_voice_channel_id=target_channel.id,
                    last_event="wchodzę za Muchą",
                    last_event_at=time.time(),
                )

        except discord.Forbidden:
            print(
                f"[{guild.name}] Brak uprawnień do kanału: "
                f"{target_channel.name}"
            )
        except asyncio.TimeoutError:
            print(f"[{guild.name}] Timeout podczas łączenia z voice.")
        except discord.ClientException as exc:
            print(f"[{guild.name}] Błąd klienta voice: {exc}")
        except Exception as exc:
            print(
                f"[{guild.name}] Błąd voice: "
                f"{type(exc).__name__}: {exc}"
            )


async def chase_round(guild: discord.Guild):
    print(
        f"[{guild.name}] === START rundy pościgu "
        f"({CHASE_DURATION}s) ==="
    )
    active_chases[guild.id] = True
    round_started_at = time.time()
    update_status(
        guild,
        active_chase=True,
        state="CHASE",
        round_started_at=round_started_at,
        round_ends_at=round_started_at + CHASE_DURATION,
        next_round_at=round_started_at + CHASE_INTERVAL,
        last_event="start rundy pościgu",
        last_event_at=round_started_at,
    )

    try:
        await follow_mucha(guild)
        await asyncio.sleep(CHASE_DURATION)
    finally:
        active_chases[guild.id] = False
        await disconnect_from_voice(guild)
        update_status(
            guild,
            active_chase=False,
            state="WAITING",
            current_voice_channel=None,
            current_voice_channel_id=None,
            last_event="koniec rundy pościgu",
            last_event_at=time.time(),
        )
        print(
            f"[{guild.name}] === KONIEC rundy "
            "-> wychodzę z voice ==="
        )


async def chase_loop(guild: discord.Guild):
    while not client.is_closed():
        round_started_at = time.time()
        try:
            await chase_round(guild)
        except Exception as exc:
            print(
                f"[{guild.name}] Błąd rundy: "
                f"{type(exc).__name__}: {exc}"
            )
            active_chases[guild.id] = False
            await disconnect_from_voice(guild)

        # Kolejna runda startuje 10 minut od początku poprzedniej.
        next_round_at = round_started_at + CHASE_INTERVAL
        pause = max(0.0, next_round_at - time.time())
        update_status(
            guild,
            next_round_at=next_round_at,
            state="WAITING",
        )
        print(f"[{guild.name}] Następna runda za {pause:.1f} s.")
        await asyncio.sleep(pause)


@client.event
async def on_ready():
    print("=" * 60)
    print(f"Zalogowano jako: {client.user} ({client.user.id})")
    print(f"discord.py: {discord.__version__}")
    print(f"Ścigam Muchę o ID: {MUCHA_BOT_ID}")
    print(
        f"Runda: {CHASE_DURATION}s | "
        f"start co: {CHASE_INTERVAL}s"
    )
    print("=" * 60)
    update_status(
        online=True,
        bot={
            "id": client.user.id,
            "name": str(client.user),
        },
    )
    for guild in client.guilds:
        update_status(
            guild,
            active_chase=active_chases.get(guild.id, False),
            state="CHASE" if active_chases.get(guild.id, False) else "WAITING",
        )

    # on_ready może odpalić się ponownie po reconnect.
    if getattr(client, "_chase_loops_started", False):
        return

    client._chase_loops_started = True

    for guild in client.guilds:
        asyncio.create_task(chase_loop(guild))


@client.event
async def on_voice_state_update(member, before, after):
    if member.id != MUCHA_BOT_ID:
        return

    if not active_chases.get(member.guild.id, False):
        return

    print(
        f"[{member.guild.name}] Mucha: "
        f"{getattr(before.channel, 'name', None)} -> "
        f"{getattr(after.channel, 'name', None)}"
    )

    asyncio.create_task(follow_mucha(member.guild))


if not TOKEN:
    raise RuntimeError("Brak DISCORD_TOKEN w pliku .env")

if not MUCHA_BOT_ID:
    raise RuntimeError("Brak poprawnego MUCHA_BOT_ID w pliku .env")

client.run(TOKEN)
