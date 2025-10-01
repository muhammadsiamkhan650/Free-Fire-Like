import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from datetime import datetime
import json
import os
import asyncio
from dotenv import load_dotenv

load_dotenv()
API_URL = os.getenv("API_URL")
CONFIG_FILE = "like_channels.json"
DAILY_FILE = "daily_usage.json"

class LikeCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.api_host = API_URL
        self.config_data = self.load_config()
        self.cooldowns = {}
        self.session = aiohttp.ClientSession()
        self.daily_usage = self.load_daily_usage()

    # =================== HELPER ===================
    async def send_temp(self, ctx, content=None, embed=None, ephemeral=False, delay=5):
        """Send a temporary message that deletes itself after delay seconds"""
        try:
            return await ctx.send(content=content, embed=embed, ephemeral=ephemeral, delete_after=delay)
        except Exception as e:
            print(f"[send_temp error] {e}")

    # =================== CONFIG HANDLING ===================
    def load_config(self):
        default_config = {"servers": {}}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    loaded_config = json.load(f)
                    loaded_config.setdefault("servers", {})
                    return loaded_config
            except json.JSONDecodeError:
                print(
                    f"WARNING: The configuration file '{CONFIG_FILE}' is corrupt or empty. Resetting to default configuration."
                )
        self.save_config(default_config)
        return default_config

    def save_config(self, config_to_save=None):
        data_to_save = config_to_save if config_to_save is not None else self.config_data
        temp_file = CONFIG_FILE + ".tmp"
        with open(temp_file, "w") as f:
            json.dump(data_to_save, f, indent=4)
        os.replace(temp_file, CONFIG_FILE)

    # =================== DAILY LIMIT HANDLING ===================
    def load_daily_usage(self):
        if os.path.exists(DAILY_FILE):
            try:
                with open(DAILY_FILE, "r") as f:
                    return json.load(f)
            except json.JSONDecodeError:
                return {}
        return {}

    def save_daily_usage(self):
        with open(DAILY_FILE, "w") as f:
            json.dump(self.daily_usage, f, indent=4)

    async def check_daily_limit(self, ctx):
        guild_id = str(ctx.guild.id)
        premium_role_id = self.config_data["servers"].get(guild_id, {}).get("premium_role")

        # ==== PREMIUM BYPASS ====
        if premium_role_id and discord.utils.get(ctx.author.roles, id=int(premium_role_id)):
            return True, None

        user_id = str(ctx.author.id)
        today = datetime.utcnow().date().isoformat()

        if user_id not in self.daily_usage:
            self.daily_usage[user_id] = {"last_reset": today, "used": 0}

        # Reset if new day
        if self.daily_usage[user_id]["last_reset"] != today:
            self.daily_usage[user_id] = {"last_reset": today, "used": 0}

        # Normal limit = 1
        limit = 1
        if self.daily_usage[user_id]["used"] >= limit:
            return False, limit

        self.daily_usage[user_id]["used"] += 1
        self.save_daily_usage()
        return True, None

    # =================== CHANNEL CHECK ===================
    async def check_channel(self, ctx):
        if ctx.guild is None:
            return True
        guild_id = str(ctx.guild.id)
        like_channels = self.config_data["servers"].get(guild_id, {}).get("like_channels", [])
        return not like_channels or str(ctx.channel.id) in like_channels

    async def cog_load(self):
        pass

    # =================== ADMIN COMMANDS ===================
    @commands.hybrid_command(
        name="setlikechannel", description="Sets the channels where the /like command is allowed."
    )
    @commands.has_permissions(administrator=True)
    @app_commands.describe(channel="The channel to allow/disallow the /like command in.")
    async def set_like_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        if ctx.guild is None:
            return await self.send_temp(ctx, "This command can only be used in a server.")

        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        like_channels = server_config.setdefault("like_channels", [])

        channel_id_str = str(channel.id)

        if channel_id_str in like_channels:
            like_channels.remove(channel_id_str)
            self.save_config()
            await self.send_temp(ctx, f"✅ Channel {channel.mention} has been **removed**.")
        else:
            like_channels.append(channel_id_str)
            self.save_config()
            await self.send_temp(ctx, f"✅ Channel {channel.mention} is now **allowed**.")

    @commands.hybrid_command(
        name="setpremiumrole", description="Set the premium role for unlimited like access."
    )
    @commands.has_permissions(administrator=True)
    async def set_premium_role(self, ctx: commands.Context, role: discord.Role):
        guild_id = str(ctx.guild.id)
        server_config = self.config_data["servers"].setdefault(guild_id, {})
        server_config["premium_role"] = str(role.id)
        self.save_config()
        await self.send_temp(ctx, f"✅ Premium role set to {role.mention}.")

    # =================== MAIN LIKE COMMAND ===================
    @commands.hybrid_command(name="like", description="Sends likes to a Free Fire player")
    @app_commands.describe(uid="Player UID (numbers only, minimum 6 characters)")
    async def like_command(self, ctx: commands.Context, server: str = None, uid: str = None):
        is_slash = ctx.interaction is not None

        if uid is None or server is None:
            return await self.send_temp(ctx, "⚠️ UID and server are required.")

        if not await self.check_channel(ctx):
            msg = "This command is not available in this channel. Please use it in an authorized channel."
            return await self.send_temp(ctx, msg)

# Daily Limit Check
allowed, limit = await self.check_daily_limit(ctx)
if not allowed:
    embed = discord.Embed(
        title="🚫 Daily Limit Reached!",
        description=(
            f"❌ You already used your **{limit} like(s)** today.\n\n"
            f"✨ Upgrade to **Premium** role and enjoy **Unlimited Likes** 🚀"
        ),
        color=discord.Color.gold(),  # Premium golden color
        timestamp=datetime.now()
    )
    embed.set_footer(text="⏳ Limit resets every midnight (UTC)")
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/3135/3135715.png")  # VIP Icon
    # Delay set to 8 seconds for better visibility
    return await self.send_temp(ctx, embed=embed, delay=8)

        # Cooldown
        user_id = ctx.author.id
        cooldown = 30
        if user_id in self.cooldowns:
            last_used = self.cooldowns[user_id]
            remaining = cooldown - (datetime.now() - last_used).seconds
            if remaining > 0:
                return await self.send_temp(ctx, f"Please wait {remaining} seconds before using this command again.")
        self.cooldowns[user_id] = datetime.now()

        # UID Validation
        if not uid.isdigit() or len(uid) < 6:
            return await self.send_temp(ctx, "❌ Invalid UID. Must be at least 6 digits and numbers only.")

        try:
            async with ctx.typing():
                url = f"{self.api_host}/like?uid={uid}&server={server}"
                print(url)
                async with self.session.get(url) as response:
                    if response.status == 404:
                        return await self._send_player_not_found(ctx, uid)

                    if response.status != 200:
                        print(f"API Error: {response.status} - {await response.text()}")
                        return await self._send_api_error(ctx)

                    data = await response.json()

                    # === SUCCESS CASE ===
                    if data.get("status") == 1:
                        embed = discord.Embed(
                            title="👑 Panther Corporation 👑",
                            description="💖 **Likes delivered successfully!**\n✨ Perfect execution!",
                            color=0x2ECC71,
                            timestamp=datetime.now(),
                        )

                        embed.add_field(
                            name="👤 Player Info",
                            value=f"```UID  : {uid}\nName : {data.get('player','Unknown')}```",
                            inline=True,
                        )
                        embed.add_field(
                            name="🌍 Server Region",
                            value=f"```{server.upper()} Server```",
                            inline=True,
                        )

                        before = data.get("likes_before", "N/A")
                        after = data.get("likes_after", "N/A")
                        added = data.get("likes_added", 0)
                        embed.add_field(
                            name="📊 Like Status",
                            value=f"```Before: {before} likes\nAfter : {after} likes\nAdded : {added} likes```",
                            inline=False,
                        )

                        embed.add_field(
                            name="⚡ Execution Info",
                            value=f"👤 Requested by: {ctx.author.mention}\n🕒 Time: <t:{int(datetime.now().timestamp())}:R>",
                            inline=False,
                        )

                        embed.set_image(url="https://imgur.com/mXr0UDF.gif")
                        embed.set_footer(text="🔰Developer: ! 1n Only Leo")
                        embed.description += "\n🔗 JOIN : https://discord.gg/dHkkwvCkWt"

                        await ctx.send(embed=embed)

                    # === FAILED CASE ===
                    else:
                        embed = discord.Embed(
                            title="❌ LIKE FAILED",
                            description="⚠️ This UID has already received the maximum likes today.\nPlease wait **24 hours** and try again.",
                            color=0xE74C3C,
                            timestamp=datetime.now(),
                        )
                        embed.set_footer(text=f"🔰 Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
                        await self.send_temp(ctx, embed=embed)

        except asyncio.TimeoutError:
            await self._send_error_embed(ctx, "Timeout", "The server took too long to respond.")
        except Exception as e:
            print(f"Unexpected error in like_command: {e}")
            await self._send_error_embed(ctx, "Critical Error", "An unexpected error occurred. Please try again later.")

    # =================== ERROR HANDLING ===================
    async def _send_player_not_found(self, ctx, uid):
        embed = discord.Embed(
            title="Player Not Found",
            description=f"The UID {uid} does not exist or is not accessible.",
            color=0xE74C3C,
        )
        embed.add_field(
            name="Tip",
            value="Make sure that:\n- The UID is correct\n- The player is not private",
            inline=False,
        )
        await self.send_temp(ctx, embed=embed)

    async def _send_api_error(self, ctx):
        embed = discord.Embed(
            title="⚠️ Service Unavailable",
            description="The Free Fire API is not responding at the moment.",
            color=0xF39C12,
        )
        embed.add_field(name="Solution", value="Try again in a few minutes.", inline=False)
        await self.send_temp(ctx, embed=embed)

    async def _send_error_embed(self, ctx, title, description, ephemeral=False):
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red(),
            timestamp=datetime.now(),
        )
        embed.set_footer(text="An error occurred.")
        await self.send_temp(ctx, embed=embed)

    def cog_unload(self):
        self.bot.loop.create_task(self.session.close())

async def setup(bot):
    await bot.add_cog(LikeCommands(bot))
