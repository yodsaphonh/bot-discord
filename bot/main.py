import os
import asyncio
import discord
import wavelink
from discord.ext import commands
from dotenv import load_dotenv

# ---------- ENV / CONFIG ----------
load_dotenv()
TOKEN   = os.getenv("DISCORD_TOKEN")
PREFIX  = os.getenv("COMMAND_PREFIX", "!")
LL_HOST = os.getenv("LAVALINK_HOST", "127.0.0.1")
LL_PORT = int(os.getenv("LAVALINK_PORT", "2333"))
LL_PWD  = os.getenv("LAVALINK_PASSWORD", "changeme")
DEFAULT_VOLUME = int(os.getenv("DEFAULT_VOLUME", "50"))

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

# ---------- Compatibility: NodePool(เก่า) / Pool(ใหม่) ----------
HAS_NODEPOOL = hasattr(wavelink, "NodePool")  # ใน 3.3.0 จะเป็น False

def pool_nodes():
    """คืน dict ของ nodes ตาม API แต่ละรุ่น"""
    return wavelink.NodePool.nodes if HAS_NODEPOOL else getattr(wavelink.Pool, "nodes", {})

async def pool_connect():
    """เชื่อมต่อ node ตาม API แต่ละรุ่น"""
    node = wavelink.Node(uri=f"http://{LL_HOST}:{LL_PORT}", password=LL_PWD)
    if HAS_NODEPOOL:
        await wavelink.NodePool.connect(client=bot, nodes=[node])
    else:
        await wavelink.Pool.connect(client=bot, nodes=[node])

# ---------- Startup ----------
@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    # retry ต่อ node สูงสุด 6 ครั้ง (backoff)
    for i in range(6):
        try:
            # ถ้ามี node และต่อแล้ว ให้หยุด retry
            for n in pool_nodes().values():
                if getattr(n, "is_connected", False):
                    raise SystemExit
            await pool_connect()
            break
        except SystemExit:
            break
        except Exception as e:
            print(f"[Wavelink] connect attempt {i+1} failed: {e}")
            await asyncio.sleep(2 * (i + 1))

# NOTE: ใน Wavelink 3.3.0 อีเวนต์นี้ส่ง 'payload' ไม่ใช่ node ตรง ๆ
@bot.listen("on_wavelink_node_ready")
async def _node_ready(payload: wavelink.NodeReadyEventPayload):
    node = payload.node
    print(f"🎧 Lavalink node ready: {node.uri}")

# ---------- Helpers ----------
async def ensure_connected(ctx) -> wavelink.Player:
    """ให้บอทเข้า voice ของผู้ใช้ และชัวร์ว่ามี node แล้ว"""
    if not ctx.author.voice or not ctx.author.voice.channel:
        raise commands.CommandError("⚠️ เข้าห้องเสียงก่อนนะ")

    if not pool_nodes():  # เผื่อยังไม่ต่อ node
        await pool_connect()

    if ctx.voice_client and isinstance(ctx.voice_client, wavelink.Player):
        return ctx.voice_client

    player: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
    player.text_channel = ctx.channel  # เก็บไว้ใช้ส่งข้อความออโต้
    await player.set_volume(DEFAULT_VOLUME)
    return player

# ---------- Debug ----------
@bot.command()
async def nodes(ctx):
    ns = pool_nodes()
    if not ns:
        return await ctx.reply("❌ ไม่มี node ในพูล")
    lines = []
    for key, n in ns.items():
        stats = getattr(n, "stats", None)
        lines.append(
            f"- {key}: connected={getattr(n,'is_connected',None)} uri={n.uri} players={getattr(stats,'players',None)}"
        )
    await ctx.reply("\n".join(lines))

# ---------- Music Commands ----------
@bot.command()
async def join(ctx):
    await ensure_connected(ctx)
    await ctx.reply("✅ เข้าห้องเสียงแล้ว", mention_author=False)

@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        await ctx.voice_client.disconnect()
    await ctx.reply("👋 ออกจากห้องเสียงแล้ว", mention_author=False)

@bot.command()
async def play(ctx, *, query: str):
    p = await ensure_connected(ctx)
    # URL = search ตรง, ข้อความ = ค้น YouTube
    if query.startswith(("http://", "https://")):
        tracks = await wavelink.Playable.search(query)
    else:
        tracks = await wavelink.YouTubeTrack.search(query=query, return_first=False)

    if not tracks:
        return await ctx.reply("❌ ไม่เจอเพลง", mention_author=False)

    t = tracks[0]
    if p.playing:
        p.queue.put(t)
        return await ctx.reply(f"➕ เข้าคิว: **{t.title}**", mention_author=False)

    await p.play(t)
    await ctx.reply(f"🎶 กำลังเล่น: **{t.title}**", mention_author=False)

@bot.listen("on_wavelink_track_end")
async def _on_end(payload: wavelink.TrackEndEventPayload):
    p: wavelink.Player = payload.player
    if not p.queue.is_empty:
        nxt = p.queue.get()
        await p.play(nxt)
        if getattr(p, "text_channel", None):
            await p.text_channel.send(f"🎵 เล่นต่อ: **{nxt.title}**")

@bot.command()
async def pause(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p or not p.playing:
        return await ctx.reply("ℹ️ ยังไม่มีเพลงกำลังเล่น", mention_author=False)
    await p.pause()
    await ctx.reply("⏸️ พักเพลงแล้ว", mention_author=False)

@bot.command()
async def resume(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    await p.resume()
    await ctx.reply("▶️ เล่นต่อแล้ว", mention_author=False)

@bot.command()
async def skip(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p or not p.playing:
        return await ctx.reply("ℹ️ ไม่มีเพลงให้ข้าม", mention_author=False)
    await p.stop()
    await ctx.reply("⏭️ ข้ามเพลง", mention_author=False)

@bot.command()
async def stop(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    p.queue.clear()
    await p.stop()
    await ctx.reply("🛑 หยุดและล้างคิวแล้ว", mention_author=False)

@bot.command(name="np")
async def now_playing(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p or not p.current:
        return await ctx.reply("ℹ️ ไม่มีเพลงกำลังเล่น", mention_author=False)
    await ctx.reply(f"🎧 ตอนนี้: **{p.current.title}**", mention_author=False)

@bot.command()
async def queue(ctx):
    p: wavelink.Player = ctx.voice_client
    if not p or p.queue.is_empty:
        return await ctx.reply("📭 คิวว่าง", mention_author=False)
    items = list(p.queue)
    lines = [f"{i+1}. {t.title}" for i, t in enumerate(items[:10])]
    more = f"\n...และอีก {len(items)-10} เพลง" if len(items) > 10 else ""
    await ctx.reply("📜 **คิวเพลง:**\n" + "\n".join(lines) + more, mention_author=False)



# ====== VOLUME ======
@bot.command(aliases=["vol"])
async def volume(ctx, level: int):
    """ตั้งระดับเสียง 0–150"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    level = max(0, min(150, level))
    await p.set_volume(level)
    await ctx.reply(f"🔊 ตั้งเสียง = {level}", mention_author=False)

@bot.command()
async def vup(ctx, step: int = 10):
    """เพิ่มเสียงทีละ step (ดีฟอลต์ 10)"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    cur = getattr(p, "volume", 100) or 100
    new = max(0, min(150, cur + step))
    await p.set_volume(new)
    await ctx.reply(f"🔊 เพิ่มเสียงเป็น {new}", mention_author=False)

@bot.command()
async def vdown(ctx, step: int = 10):
    """ลดเสียงทีละ step (ดีฟอลต์ 10)"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    cur = getattr(p, "volume", 100) or 100
    new = max(0, min(150, cur - step))
    await p.set_volume(new)
    await ctx.reply(f"🔉 ลดเสียงเป็น {new}", mention_author=False)

# ====== BASS BOOST (EQ) — สำหรับ Wavelink 3.3.x ======
# ====== BASS BOOST (EQ) — Wavelink 3.3.0 ======
def _eq_preset(level: str) -> wavelink.Equalizer:
    level = level.lower()
    presets = {
        "off":    [],
        "light":  [(0, .15), (1, .10), (2, .05)],
        "medium": [(0, .25), (1, .20), (2, .15), (3, .10)],
        "hard":   [(0, .35), (1, .30), (2, .25), (3, .20), (4, .10)],
        "extreme":[(0, .50), (1, .45), (2, .40), (3, .30), (4, .20), (5, .10)],
    }
    bands = presets.get(level)
    if bands is None:
        raise ValueError("ระดับที่ใช้ได้: off, light, medium, hard, extreme")

    # ✅ 3.3.0: ส่งลิสต์ bands เป็นอาร์กิวเมนต์ “ตำแหน่ง” ไม่ใช้ชื่อพารามิเตอร์
    return wavelink.Equalizer(bands)

@bot.command()
async def bass(ctx, level: str):
    """ตั้งค่าเบส: off | light | medium | hard | extreme"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    try:
        eq = _eq_preset(level)
    except ValueError as e:
        return await ctx.reply(f"⚠️ {e}", mention_author=False)

    await p.set_filters(wavelink.Filters(equalizer=eq))
    await ctx.reply(f"🎚️ Bass boost: **{level.lower()}**", mention_author=False)


# ====== TIMESCALE (Wavelink 3.3.0 ใช้ 'rate' เท่านั้น) ======
@bot.command()
async def speed(ctx, value: float):
    """ปรับความเร็ว (0.5–2.0) — ใช้ timescale.rate"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    value = max(0.5, min(2.0, value))
    ts = wavelink.Timescale(rate=value)   # <-- ใช้ rate แทน speed/pitch
    await p.set_filters(wavelink.Filters(timescale=ts))
    await ctx.reply(f"⏩ Speed (rate) = {value:.2f}", mention_author=False)

@bot.command(aliases=["clearfx","fxoff","resetfx"])
async def fxreset(ctx):
    """ล้างเอฟเฟกต์ทั้งหมด"""
    p: wavelink.Player = ctx.voice_client
    if not p:
        return await ctx.reply("ℹ️ ยังไม่ได้เชื่อมต่อเสียง", mention_author=False)
    await p.set_filters(wavelink.Filters())  # ฟิลเตอร์ว่าง
    await ctx.reply("♻️ ปิดเอฟเฟกต์ทั้งหมดแล้ว", mention_author=False)


# ---------- Error handler ----------
@bot.event
async def on_command_error(ctx, error):
    await ctx.reply(f"⚠️ {error}", mention_author=False)

# ---------- Entry ----------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("กรุณาใส่ DISCORD_TOKEN ใน .env")
    bot.run(TOKEN)
