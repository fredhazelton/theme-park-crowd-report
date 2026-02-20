"""One-shot: clear ALL commands (global + guild), then re-register guild only."""
import os, asyncio, discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.env"))
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
TEST_GUILD_ID = 1471374656253591695

intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

@client.event
async def on_ready():
    guild = discord.Object(id=TEST_GUILD_ID)
    
    # 1. Clear global commands
    tree.clear_commands(guild=None)
    await tree.sync()
    print("✅ Global commands cleared")
    
    # 2. Clear guild commands
    tree.clear_commands(guild=guild)
    await tree.sync(guild=guild)
    print("✅ Guild commands cleared")
    
    # 3. Fetch to confirm
    global_cmds = await tree.fetch_commands()
    guild_cmds = await tree.fetch_commands(guild=guild)
    print(f"   Global: {[c.name for c in global_cmds]}")
    print(f"   Guild:  {[c.name for c in guild_cmds]}")
    
    await client.close()

client.run(TOKEN)
