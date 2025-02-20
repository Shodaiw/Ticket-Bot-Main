import discord
from discord import app_commands, utils
from discord.ext import commands, tasks
import os
from dotenv import load_dotenv
from datetime import datetime
import logging
import sqlite3

# Ortam değişkenlerini yükle
load_dotenv("token.env")
TOKEN = os.getenv("TOKEN")

# Loglama ayarları
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Veritabanı ayarları
DATABASE_NAME = 'tickets.db'

def create_connection():
    """Veritabanı bağlantısı oluşturur."""
    conn = None
    try:
        conn = sqlite3.connect(DATABASE_NAME)
        logger.info(f"Veritabanına bağlandı: {DATABASE_NAME}")
    except sqlite3.Error as e:
        logger.error(f"Veritabanı bağlantı hatası: {e}")
    return conn

def create_table(conn):
    """Ticket tablosunu oluşturur."""
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                status TEXT DEFAULT 'Açık',
                user_id INTEGER
            )
        """)
        conn.commit()
        logger.info("Ticket tablosu oluşturuldu veya zaten mevcut.")
    except sqlite3.Error as e:
        logger.error(f"Ticket tablosu oluşturma hatası: {e}")

# Veritabanı bağlantısını oluştur ve tabloyu oluştur
conn = create_connection()
if conn is not None:
    create_table(conn)

# Ticket Sistemi Ayarları
TICKET_CATEGORY_ID = 134212536305  # Kategori ID
DESTEK_EKIBI_ROL_ID = 134208509  # Destek Ekibi Rolü
ADMIN_ROL_ID = 1342085093 # Admin Rolü
YETKILI_ROL_ID =  13420850 # Yetkili Rol ID'si (Buraya kendi rol ID'nizi girin)

def get_ticket_status(conn, channel_id: int) -> str:
    """Ticket durumunu veritabanından alır."""
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT status FROM tickets WHERE channel_id = ?", (channel_id,))
        result = cursor.fetchone()
        return result[0] if result else 'Açık'
    except sqlite3.Error as e:
        logger.error(f"Ticket durumu alma hatası: {e}")
        return 'Açık'

def set_ticket_status(conn, channel_id: int, status: str):
    """Ticket durumunu veritabanında günceller."""
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE tickets SET status = ? WHERE channel_id = ?", (status, channel_id))
        conn.commit()
        logger.info(f"Ticket durumu güncellendi: {channel_id} -> {status}")
    except sqlite3.Error as e:
        logger.error(f"Ticket durumu güncelleme hatası: {e}")

def create_ticket_entry(conn, channel_id: int, user_id: int):
    """Yeni ticket kaydını veritabanına ekler."""
    try:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO tickets (channel_id, user_id) VALUES (?, ?)", (channel_id, user_id))
        conn.commit()
        logger.info(f"Yeni ticket oluşturuldu: channel_id={channel_id}, user_id={user_id}")
    except sqlite3.Error as e:
        logger.error(f"Yeni ticket oluşturma hatası: {e}")

class StatusSelect(discord.ui.Select):
    """Ticket durumunu değiştirmek için kullanılan seçim menüsü."""
    def __init__(self, channel_id: int):
        self.channel_id = channel_id
        options = [
            discord.SelectOption(label="Açık", value="Açık", description="Ticket hala açık ve çözülmeyi bekliyor."),
            discord.SelectOption(label="Beklemede", value="Beklemede", description="Ticket, kullanıcıdan veya üçüncü bir taraftan yanıt bekliyor."),
            discord.SelectOption(label="Çözüldü", value="Çözüldü", description="Ticket çözüldü, onay bekleniyor."),
            discord.SelectOption(label="Kapatıldı", value="Kapatıldı", description="Ticket tamamen çözüldü ve kapatıldı.")
        ]
        super().__init__(placeholder="Ticket Durumunu Seçin...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        """Durum seçimi yapıldığında çalışacak fonksiyon."""
        status = self.values[0]
        set_ticket_status(conn, self.channel_id, status)
        embed = interaction.message.embeds[0]
        embed.set_field_at(0, name="Durum", value=status, inline=True)
        await interaction.message.edit(embed=embed)
        await interaction.response.defer()
        logger.info(f"Ticket durumu güncellendi: {self.channel_id} -> {status} ({interaction.user})")

class TicketView(discord.ui.View):
    """Ticket işlemleri için kullanılan butonları içeren görünüm."""
    def __init__(self, user: discord.Member, channel_id: int):
        super().__init__(timeout=None)
        self.user = user
        self.channel_id = channel_id
        self.add_item(StatusSelect(channel_id))

    @discord.ui.button(label="🔒 Talebi Kapat", style=discord.ButtonStyle.red, custom_id="close_ticket")
    async def close_ticket_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ticket kapatma butonu."""
        await interaction.response.defer(ephemeral=True)

        # Yetki kontrolü
        is_support_team = any(role.id == DESTEK_EKIBI_ROL_ID for role in interaction.user.roles)
        if interaction.user != self.user and not is_support_team:
            await interaction.followup.send("Bu ticket'ı kapatma yetkiniz yok.", ephemeral=True)
            return

        try:
            # Ticket'ı kapat
            embed = interaction.message.embeds[0]
            embed.description = f"Bu ticket {interaction.user.mention} tarafından kapatıldı."
            await interaction.message.edit(embed=embed, view=None)
            await interaction.channel.edit(name=f"kapali-{interaction.channel.name}", overwrites={
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False)
            })
            logger.info(f"Ticket kapatıldı: {interaction.channel.id} ({interaction.user})")

        except discord.Forbidden:
            logger.error("Ticket kapatma yetkisi yok.")
            await interaction.followup.send("Ticket kapatılamadı. Yetkim yok.", ephemeral=True)
        except Exception as e:
            logger.exception(f"Ticket kapatılırken bir hata oluştu: {e}")
            await interaction.followup.send("Ticket kapatılırken bir hata oluştu.", ephemeral=True)

    @discord.ui.button(label="📣 Yetkili Çağır", style=discord.ButtonStyle.primary, custom_id="summon_yt")
    async def summon_yt_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Yetkili çağırma butonu."""
        await interaction.response.defer(ephemeral=True)

        # Yetkili rolünü al
        role = interaction.guild.get_role(YETKILI_ROL_ID)
        if role:
            await interaction.channel.send(f"{role.mention}, bu ticket'a bakabilir misiniz?")
            logger.info(f"Yetkili çağrıldı: {interaction.channel.id} ({interaction.user})")
        else:
            await interaction.followup.send("Yetkili rolü bulunamadı. Lütfen bot yöneticisine başvurun.", ephemeral=True)
            logger.error(f"Yetkili rolü bulunamadı. (Rol ID: {YETKILI_ROL_ID})")

class TicketLauncher(discord.ui.View):
    """Ticket oluşturma butonu için kullanılan görünüm."""
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎟️ Destek Talebi Oluştur", style=discord.ButtonStyle.blurple, custom_id="ticket_button")
    async def ticket_button_callback(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Ticket oluşturma butonu."""
        await interaction.response.defer(ephemeral=True)

        # Ticket kanalının adını oluştur
        ticket_name = f"destek-{interaction.user.name}-{interaction.user.discriminator}"

        # Aynı isimde bir kanalın olup olmadığını kontrol et
        ticket_channel = utils.get(interaction.guild.text_channels, name=ticket_name)
        if ticket_channel:
            await interaction.followup.send(f"Zaten açık bir destek talebiniz var: {ticket_channel.mention}", ephemeral=True)
            return

        try:
            # İzinleri ayarla
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True, read_message_history=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            }

            # Kategori kanalını al
            category = interaction.guild.get_channel(TICKET_CATEGORY_ID)
            if not category or not isinstance(category, discord.CategoryChannel):
                logger.error(f"Geçersiz ticket kategori ID: {TICKET_CATEGORY_ID}")
                await interaction.followup.send("Ticket oluşturulurken bir hata oluştu.", ephemeral=True)
                return

            # Ticket kanalını oluştur
            ticket_channel = await interaction.guild.create_text_channel(
                ticket_name,
                category=category,
                overwrites=overwrites,
                reason=f"Destek talebi oluşturuldu: {interaction.user}",
            )
            logger.info(f"Ticket oluşturuldu: {ticket_channel.id} ({interaction.user})")

            # Ticket kaydını veritabanına ekle
            create_ticket_entry(conn, ticket_channel.id, interaction.user.id)

            # Embed mesajı oluştur
            embed = discord.Embed(
                title="📩 Destek Talebi",
                description=f"Merhaba {interaction.user.mention}, bir destek talebi oluşturdunuz!",
                color=discord.Color.green(),
                timestamp=datetime.utcnow()
            )
            embed.add_field(name="Durum", value="Açık", inline=True)
            embed.set_image(url="https://media.giphy.com/media/l41lZxzroU33typuU/giphy.gif")
            embed.set_footer(text=f"Ticket ID: {ticket_channel.id} | Oluşturan: {interaction.user.name}#{interaction.user.discriminator}")

            # Ticket görünümünü ve mesajını gönder
            view = TicketView(interaction.user, ticket_channel.id)
            await ticket_channel.send(embed=embed, view=view)
            await interaction.followup.send(f"Ticket başarıyla oluşturuldu: {ticket_channel.mention}", ephemeral=True)

        except discord.Forbidden:
            logger.error("Ticket oluşturma yetkisi yok.")
            await interaction.followup.send("Ticket oluşturulamadı. Yetkim yok.", ephemeral=True)
        except Exception as e:
            logger.exception(f"Ticket oluşturulurken bir hata oluştu: {e}")
            await interaction.followup.send("Ticket oluşturulurken bir hata oluştu.", ephemeral=True)

class AClient(commands.Bot):
    """Discord bot sınıfı."""
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned_or("!"), intents=intents)
        self.synced = False
        self.added = False

    async def on_ready(self):
        """Bot hazır olduğunda çalışacak fonksiyon."""
        await self.wait_until_ready()
        if not self.synced:
            try:
                await self.tree.sync(guild=discord.Object(id=1342083609288376320))
                logger.info("Komutlar senkronize edildi.")
            except Exception as e:
                logger.error(f"Komut senkronizasyon hatası: {e}")
            self.synced = True
        if not self.added:
            self.add_view(TicketLauncher())
            self.added = True
        logger.info(f"Bot giriş yaptı: {self.user} (ID: {self.user.id})")

# Bot nesnesini oluştur
client = AClient()
tree = client.tree

@tree.command(guild=discord.Object(id=1342083609288376320), name="destek", description="Destek sistemi başlatır")
async def ticketing(interaction: discord.Interaction):
    """Destek sistemi başlatma komutu."""
    embed = discord.Embed(title="🛠️ Desteğe mi ihtiyacınız var?", description="Aşağıdaki butona tıklayarak destek talebi oluşturabilirsiniz!", color=discord.Color.blue())
    embed.set_thumbnail(url="https://media.giphy.com/media/Y01jP8QeLOox2/giphy.gif")
    await interaction.channel.send(embed=embed, view=TicketLauncher())
    await interaction.response.send_message("Destek sistemi başlatıldı!", ephemeral=True)
    logger.info(f"Destek sistemi başlatıldı. ({interaction.user})")

# Botu çalıştır
if __name__ == "__main__":
    if not TOKEN:
        logger.error("TOKEN bulunamadı! Lütfen token.env dosyanızı kontrol edin.")
    else:
        client.run(TOKEN)

if conn:
    conn.close()
    logger.info("Veritabanı bağlantısı kapatıldı.")