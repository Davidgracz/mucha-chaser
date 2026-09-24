import os
import asyncio
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
            return

        try:
            if voice and voice.is_connected():
                if voice.channel.id != target_channel.id:
                    print(
                        f"[{guild.name}] Mucha uciekła na: "
                        f"{target_channel.name} -> gonię!"
                    )
                    await voice.move_to(target_channel)
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

    try:
        await follow_mucha(guild)
        await asyncio.sleep(CHASE_DURATION)
    finally:
        active_chases[guild.id] = False
        await disconnect_from_voice(guild)
        print(
            f"[{guild.name}] === KONIEC rundy "
            "-> wychodzę z voice ==="
        )


async def chase_loop(guild: discord.Guild):
    while not client.is_closed():
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
        pause = max(0, CHASE_INTERVAL - CHASE_DURATION)
        print(f"[{guild.name}] Następna runda za {pause} s.")
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
