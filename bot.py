"""
IgrzyskaMC.PL - Discord Bot
Moduły: Tickety (ze zdjęciami), Centrum Pomocy (ze zdjęciami), Ankiety, Propozycje,
        Błędy, Powitania, Konkursy/Giveaway'e, Ogłoszenia

Wymagane zmienne środowiskowe:
  DISCORD_TOKEN   - token bota
  TEST_GUILD_ID   - (opcjonalnie) ID serwera do natychmiastowej synchronizacji komend

=== JAK TO DZIAŁA (skrót) ===
- Propozycje: ustaw kanał (/konfiguracja kanal Propozycje). Każda wiadomość napisana na tym
  kanale (tekst i/lub zdjęcie) zamienia się automatycznie w kartę propozycji z reakcjami 👍/👎.
  Można też skorzystać z przycisku "Napisz swoją propozycję" (/propozycje panel) - to samo,
  tylko przez okienko (bez zdjęcia, bo Discord nie pozwala dodawać zdjęć w oknach/modalach).
- Ankiety: ustaw kanał (/konfiguracja kanal Ankiety). Każda wiadomość na tym kanale zamienia
  się w ankietę tak/nie - liczbę głosów pokazują natywne reakcje ✅ / ❌ Discorda.
- Wszystko (propozycje, błędy, ankiety, ogłoszenia, konkursy) da się edytować i usuwać
  komendami staffu/adminów - patrz /pomoc.
"""

import os
import io
import re
import json
import random
import asyncio
import datetime
from typing import Optional, List

import discord
from discord.ext import commands, tasks
from discord import app_commands

# ========================
#   KONFIGURACJA
# ========================

CONFIG_PLIK = "config.json"

DEFAULT_CONFIG = {
    "nazwa_serwera": "IgrzyskaMC.PL",

    "kolory": {
        "propozycje": 0x5865F2,
        "bledy": 0xED4245,
        "info": 0x57F287,
        "ankiety": 0xFEE75C,
        "pomoc": 0x5865F2,
        "tickety": 0x5865F2,
        "powitanie": 0x57F287,
        "konkursy": 0x57F287,
    },

    "obrazki": {
        "powitanie": "",
        "konkursy": "",
    },

    "kanaly": {
        "tickety_panel": 0,
        "tickety_kategoria": 0,
        "tickety_log": 0,
        "centrum_pomocy": 0,
        "propozycje": 0,
        "ankiety": 0,
        "bledy": 0,
        "ogloszenia": 0,
        "powitania": 0,
        "konkursy": 0,
    },

    "role": {
        "staff": 0,
        "powiadomienia_propozycje": 0,
        "powiadomienia_bledy": 0,
    },

    "liczniki": {
        "propozycja": 0, "blad": 0, "ankieta": 0, "ticket": 0,
        "faq": 0, "ogloszenie": 0, "konkurs": 0,
    },

    "powitanie_tresc": (
        "» **Hejka {mention}!** Miło Cię tu widzieć, rozgość się!\n"
        "» Jesteś naszym **{ilosc}** członkiem na serwerze."
    ),

    "propozycje_dane": {},
    "bledy_dane": {},
    "ankiety_dane": {},
    "tickety_dane": {},
    "ogloszenia_dane": {},
    "konkursy_dane": {},
    "faq": [],
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PLIK):
        with open(CONFIG_PLIK, "r", encoding="utf-8") as f:
            dane = json.load(f)

        def uzupelnij(domyslne, aktualne):
            for klucz, wartosc in domyslne.items():
                if klucz not in aktualne:
                    aktualne[klucz] = wartosc
                elif isinstance(wartosc, dict) and isinstance(aktualne[klucz], dict):
                    uzupelnij(wartosc, aktualne[klucz])

        uzupelnij(DEFAULT_CONFIG, dane)
        return dane
    return json.loads(json.dumps(DEFAULT_CONFIG))


CONFIG = load_config()


def save_config():
    with open(CONFIG_PLIK, "w", encoding="utf-8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=2)


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


# ========================
#   BOT
# ========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))


def is_admin(interaction: discord.Interaction) -> bool:
    return bool(interaction.user.guild_permissions.administrator)


def is_staff(interaction: discord.Interaction) -> bool:
    if is_admin(interaction):
        return True
    rola_id = CONFIG["role"].get("staff")
    if rola_id:
        rola = interaction.guild.get_role(rola_id)
        if rola and rola in interaction.user.roles:
            return True
    return False


def nastepne_id(klucz: str) -> str:
    CONFIG["liczniki"][klucz] = CONFIG["liczniki"].get(klucz, 0) + 1
    save_config()
    return str(CONFIG["liczniki"][klucz])


DLUGOSC_JEDNOSTKI = {"d": "days", "h": "hours", "m": "minutes", "s": "seconds"}
WZORZEC_CZASU = re.compile(r"(\d+)\s*(d|h|m|s)", re.IGNORECASE)


def parsuj_czas(tekst: str) -> Optional[datetime.timedelta]:
    dopasowania = WZORZEC_CZASU.findall(tekst.strip())
    if not dopasowania:
        return None
    wartosci = {"days": 0, "hours": 0, "minutes": 0, "seconds": 0}
    for liczba, jednostka in dopasowania:
        wartosci[DLUGOSC_JEDNOSTKI[jednostka.lower()]] += int(liczba)
    delta = datetime.timedelta(**wartosci)
    return delta if delta.total_seconds() > 0 else None


def forma_osob(ilosc: int) -> str:
    if ilosc == 1:
        return "osoba"
    if 2 <= ilosc % 10 <= 4 and not (12 <= ilosc % 100 <= 14):
        return "osoby"
    return "osób"


def znajdz_obrazek(message: discord.Message) -> Optional[str]:
    """Zwraca URL pierwszego załączonego zdjęcia w wiadomości (jeśli jest)."""
    for zal in message.attachments:
        if zal.content_type and zal.content_type.startswith("image/"):
            return zal.url
        if zal.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
            return zal.url
    return None


# ========================
#   DESIGN (wygląd kart - nagłówek w bloku kodu + szare "cytowanie" treści,
#   dokładnie w stylu bota-wzoru)
# ========================

def header_text(sekcja: str) -> discord.ui.TextDisplay:
    nazwa = CONFIG.get("nazwa_serwera", "Bot").upper()
    return discord.ui.TextDisplay(f"```\n🎮 {nazwa} X {sekcja.upper()}\n```")


def cytuj(tekst: str) -> str:
    linie = []
    for linia in tekst.split("\n"):
        linie.append(f"> {linia}" if linia.strip() else "")
    return "\n".join(linie)


def get_kolor(typ: str) -> discord.Color:
    wartosc = CONFIG["kolory"].get(typ, 0x5865F2)
    return discord.Color(wartosc)


def footer_line(sekcja: str) -> str:
    rok = datetime.datetime.now().year
    nazwa = CONFIG.get("nazwa_serwera", "Bot")
    return f"-# © {rok} {nazwa} x {sekcja}"


class PanelView(discord.ui.LayoutView):
    """Generyczna 'karta' w stylu bota-wzoru: nagłówek w ramce, treść cytowana szarą kreską,
    opcjonalny obrazek, opcjonalne przyciski/select w tej samej ramce, stopka z copyrightem."""

    def __init__(self, sekcja: str, opis: str, typ_koloru: str = "pomoc",
                 items: Optional[List[discord.ui.Item]] = None,
                 obrazek_url: Optional[str] = None):
        super().__init__(timeout=None)

        dzieci: List[discord.ui.Item] = [header_text(sekcja), discord.ui.Separator(),
                                          discord.ui.TextDisplay(cytuj(opis))]

        if obrazek_url:
            dzieci.append(discord.ui.Separator())
            dzieci.append(discord.ui.MediaGallery(discord.MediaGalleryItem(obrazek_url)))

        if items:
            dzieci.append(discord.ui.Separator())
            dzieci.append(discord.ui.ActionRow(*items))

        dzieci.append(discord.ui.Separator(spacing=discord.SeparatorSpacing.small))
        dzieci.append(discord.ui.TextDisplay(footer_line(sekcja)))

        self.container = discord.ui.Container(*dzieci, accent_color=get_kolor(typ_koloru))
        self.add_item(self.container)


async def wyslij_karte(kanal: discord.abc.Messageable, sekcja: str, opis: str,
                        typ_koloru: str = "pomoc", obrazek_url: Optional[str] = None):
    """Jednorazowa karta (np. wynik konkursu, zamknięcie ticketu) w tym samym stylu co panele."""
    return await kanal.send(view=PanelView(sekcja, opis, typ_koloru, obrazek_url=obrazek_url))


def karta(tytul: str, opis: str, kolor: int, stopka: Optional[str] = None) -> discord.Embed:
    """Klasyczny embed w stylu 'ogłoszenia/changelogu' (kolorowy pasek z boku, pogrubiony
    tytuł, stopka z copyrightem i datą) - używany tylko dla modułu Ogłoszeń."""
    embed = discord.Embed(title=tytul, description=opis, color=kolor)
    nazwa = CONFIG.get("nazwa_serwera", "Bot")
    rok = datetime.datetime.now().year
    embed.set_footer(text=stopka or f"🎮 Copyright {nazwa} - {rok}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return embed


# ========================
#   PROPOZYCJE i BŁĘDY (wspólny system "zgłoszeń")
# ========================

ZGLOSZENIA_TYPY = {
    "propozycja": {
        "nazwa": "Propozycja", "sekcja": "Propozycje", "kolor": "propozycje",
        "emoji_przycisku": "💡", "etykieta_przycisku": "Napisz swoją propozycję",
        "magazyn": "propozycje_dane", "rola_powiadomien": "powiadomienia_propozycje",
        "kanal": "propozycje", "status_startowy": "Rozpatrywana", "reakcje": ["👍", "👎"],
        "etykieta_tresc": "Treść propozycji",
        "stopka_dodatkowa": "Zagłosuj na tę propozycję za pomocą emotek niżej!",
    },
    "blad": {
        "nazwa": "Zgłoszenie błędu", "sekcja": "Błędy", "kolor": "bledy",
        "emoji_przycisku": "🐞", "etykieta_przycisku": "Zgłoś błąd",
        "magazyn": "bledy_dane", "rola_powiadomien": "powiadomienia_bledy",
        "kanal": "bledy", "status_startowy": "Nowe zgłoszenie", "reakcje": [],
        "etykieta_tresc": "Opis błędu (co się dzieje, jak to odtworzyć)",
        "stopka_dodatkowa": None,
    },
}


class ZgloszenieModal(discord.ui.Modal):
    def __init__(self, typ: str):
        dane = ZGLOSZENIA_TYPY[typ]
        super().__init__(title=f"Nowe: {dane['nazwa']}")
        self.typ = typ
        self.tryb = discord.ui.TextInput(label="Na jaki tryb / serwer?", max_length=100,
                                          placeholder="np. SkyPvP", required=False)
        self.tresc = discord.ui.TextInput(label=dane["etykieta_tresc"][:45],
                                           style=discord.TextStyle.paragraph, max_length=1000)
        self.add_item(self.tryb)
        self.add_item(self.tresc)

    async def on_submit(self, interaction: discord.Interaction):
        dane = ZGLOSZENIA_TYPY[self.typ]
        kanal_id = CONFIG["kanaly"].get(dane["kanal"])
        kanal = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
        if kanal is None:
            await interaction.response.send_message("⚠️ Kanał docelowy nie jest jeszcze ustawiony (zapytaj administrację).", ephemeral=True)
            return

        wpis_id = nastepne_id(self.typ)
        CONFIG[dane["magazyn"]][wpis_id] = {
            "autor_id": interaction.user.id,
            "autor_nazwa": interaction.user.display_name,
            "tryb": self.tryb.value,
            "tresc": self.tresc.value,
            "obrazek": None,
            "kanal_id": kanal.id,
            "message_id": 0,
            "status": dane["status_startowy"],
        }
        save_config()

        wiadomosc = await kanal.send(view=build_zgloszenie_panelview(self.typ, wpis_id))
        for reakcja in dane["reakcje"]:
            try:
                await wiadomosc.add_reaction(reakcja)
            except discord.HTTPException:
                pass

        CONFIG[dane["magazyn"]][wpis_id]["message_id"] = wiadomosc.id
        save_config()

        rola_id = CONFIG["role"].get(dane["rola_powiadomien"])
        if rola_id:
            rola = interaction.guild.get_role(rola_id)
            if rola:
                await kanal.send(f"🔔 {rola.mention} — nowe zgłoszenie czeka!",
                                  allowed_mentions=discord.AllowedMentions(roles=True))

        await interaction.response.send_message(f"✅ {dane['nazwa']} **#{wpis_id}** została wysłana na {kanal.mention}!", ephemeral=True)


def build_zgloszenie_panelview(typ: str, wpis_id: str) -> PanelView:
    dane = ZGLOSZENIA_TYPY[typ]
    wpis = CONFIG[dane["magazyn"]][wpis_id]

    naglowek = f"**{dane['nazwa']} od: {wpis['autor_nazwa']}**"
    if wpis.get("tryb"):
        naglowek += f", na tryb: **{wpis['tryb']}**"

    linie = [naglowek, "", wpis["tresc"] or "*(brak treści — dodano zdjęcie)*", ""]
    if dane["stopka_dodatkowa"]:
        linie.append(f"*{dane['stopka_dodatkowa']}*")
    linie.append(f"*Status: {wpis['status']} • #{wpis_id}*")
    opis = "\n".join(linie)

    return PanelView(dane["sekcja"], opis, dane["kolor"], obrazek_url=wpis.get("obrazek"))


async def zmien_status_zgloszenia(bot_instance: commands.Bot, typ: str, wpis_id: str, nowy_status: str) -> bool:
    dane = ZGLOSZENIA_TYPY[typ]
    wpis = CONFIG[dane["magazyn"]].get(wpis_id)
    if not wpis:
        return False
    wpis["status"] = nowy_status
    save_config()
    kanal = bot_instance.get_channel(wpis["kanal_id"])
    if kanal:
        try:
            wiadomosc = await kanal.fetch_message(wpis["message_id"])
            await wiadomosc.edit(view=build_zgloszenie_panelview(typ, wpis_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    return True


class ZgloszeniePanel(discord.ui.LayoutView):
    def __init__(self, typ: str):
        super().__init__(timeout=None)
        dane = ZGLOSZENIA_TYPY[typ]
        self.typ = typ

        przycisk_napisz = discord.ui.Button(label=dane["etykieta_przycisku"], emoji=dane["emoji_przycisku"],
                                             style=discord.ButtonStyle.primary,
                                             custom_id=f"igrzyskamc:zgloszenie:{typ}:napisz")
        przycisk_napisz.callback = self.napisz

        opis = ("Masz pomysł na zmianę w grze? Kliknij przycisk niżej albo napisz od razu na tym "
                "kanale (możesz dodać zdjęcie) - obie drogi trafiają w to samo miejsce!\n"
                "Głosuj na propozycje innych reakcjami 👍/👎 pod każdym zgłoszeniem.") if typ == "propozycja" else (
                "Znalazłeś błąd w grze lub na serwerze? Kliknij przycisk niżej i opisz co się dzieje - "
                "im dokładniej, tym szybciej to naprawimy!")

        items = [przycisk_napisz]

        dzieci = [header_text(dane["sekcja"]), discord.ui.Separator(),
                  discord.ui.TextDisplay(cytuj(opis)), discord.ui.Separator(),
                  discord.ui.ActionRow(*items),
                  discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                  discord.ui.TextDisplay(footer_line(dane["sekcja"]))]
        self.container = discord.ui.Container(*dzieci, accent_color=get_kolor(dane["kolor"]))
        self.add_item(self.container)

    async def napisz(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ZgloszenieModal(self.typ))


propozycje_group = app_commands.Group(name="propozycje", description="System propozycji od graczy")
bledy_group = app_commands.Group(name="bledy", description="System zgłaszania błędów")


@propozycje_group.command(name="panel", description="Wysyła panel propozycji (przycisk + info)")
async def propozycje_panel(interaction: discord.Interaction, kanal: Optional[discord.TextChannel] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("propozycje")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
    await docelowy.send(view=ZgloszeniePanel("propozycja"))
    await interaction.response.send_message(f"✅ Panel propozycji wysłany na {docelowy.mention}.", ephemeral=True)


@propozycje_group.command(name="status", description="Zmienia status propozycji")
@app_commands.describe(id="ID propozycji")
@app_commands.choices(status=[
    app_commands.Choice(name="Rozpatrywana", value="Rozpatrywana"),
    app_commands.Choice(name="Przyjęta ✅", value="Przyjęta ✅"),
    app_commands.Choice(name="Odrzucona ❌", value="Odrzucona ❌"),
])
async def propozycje_status(interaction: discord.Interaction, id: str, status: app_commands.Choice[str]):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    ok = await zmien_status_zgloszenia(bot, "propozycja", id, status.value)
    if not ok:
        await interaction.response.send_message("⚠️ Nie znaleziono propozycji o takim ID.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Status propozycji **#{id}** zmieniony na: {status.value}", ephemeral=True)


@propozycje_group.command(name="usun", description="Usuwa propozycję")
async def propozycje_usun(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["propozycje_dane"].pop(id, None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono propozycji o takim ID.", ephemeral=True)
        return
    save_config()
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await interaction.response.send_message(f"✅ Usunięto propozycję **#{id}**.", ephemeral=True)


@bledy_group.command(name="panel", description="Wysyła panel zgłaszania błędów")
async def bledy_panel(interaction: discord.Interaction, kanal: Optional[discord.TextChannel] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("bledy")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
    await docelowy.send(view=ZgloszeniePanel("blad"))
    await interaction.response.send_message(f"✅ Panel błędów wysłany na {docelowy.mention}.", ephemeral=True)


@bledy_group.command(name="status", description="Zmienia status zgłoszenia błędu")
@app_commands.describe(id="ID zgłoszenia")
@app_commands.choices(status=[
    app_commands.Choice(name="Nowe zgłoszenie", value="Nowe zgłoszenie"),
    app_commands.Choice(name="W trakcie naprawy 🔧", value="W trakcie naprawy 🔧"),
    app_commands.Choice(name="Naprawione ✅", value="Naprawione ✅"),
    app_commands.Choice(name="Odrzucone ❌", value="Odrzucone ❌"),
])
async def bledy_status(interaction: discord.Interaction, id: str, status: app_commands.Choice[str]):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    ok = await zmien_status_zgloszenia(bot, "blad", id, status.value)
    if not ok:
        await interaction.response.send_message("⚠️ Nie znaleziono zgłoszenia o takim ID.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Status zgłoszenia **#{id}** zmieniony na: {status.value}", ephemeral=True)


@bledy_group.command(name="usun", description="Usuwa zgłoszenie błędu")
async def bledy_usun(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["bledy_dane"].pop(id, None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono zgłoszenia o takim ID.", ephemeral=True)
        return
    save_config()
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await interaction.response.send_message(f"✅ Usunięto zgłoszenie **#{id}**.", ephemeral=True)


# ========================
#   AUTOMATYCZNA ZAMIANA WIADOMOŚCI NA WYZNACZONYCH KANAŁACH
#   (Propozycje i Ankiety - napisz na kanale, a bot zrobi z tego kartę)
# ========================

async def obsluz_wiadomosc_propozycji(message: discord.Message):
    tresc = message.content.strip()
    obrazek = znajdz_obrazek(message)
    if not tresc and not obrazek:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        return

    wpis_id = nastepne_id("propozycja")
    CONFIG["propozycje_dane"][wpis_id] = {
        "autor_id": message.author.id,
        "autor_nazwa": message.author.display_name,
        "tryb": "",
        "tresc": tresc,
        "obrazek": obrazek,
        "kanal_id": message.channel.id,
        "message_id": 0,
        "status": ZGLOSZENIA_TYPY["propozycja"]["status_startowy"],
    }
    save_config()

    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    wiadomosc = await message.channel.send(view=build_zgloszenie_panelview("propozycja", wpis_id))
    for reakcja in ZGLOSZENIA_TYPY["propozycja"]["reakcje"]:
        try:
            await wiadomosc.add_reaction(reakcja)
        except discord.HTTPException:
            pass

    CONFIG["propozycje_dane"][wpis_id]["message_id"] = wiadomosc.id
    save_config()

    rola_id = CONFIG["role"].get("powiadomienia_propozycje")
    if rola_id:
        rola = message.guild.get_role(rola_id)
        if rola:
            await message.channel.send(f"🔔 {rola.mention} — nowa propozycja czeka!",
                                        allowed_mentions=discord.AllowedMentions(roles=True))


async def obsluz_wiadomosc_ankiety(message: discord.Message):
    tresc = message.content.strip()
    obrazek = znajdz_obrazek(message)
    if not tresc and not obrazek:
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound):
            pass
        return

    ankieta_id = nastepne_id("ankieta")
    CONFIG["ankiety_dane"][ankieta_id] = {
        "autor_id": message.author.id,
        "autor_nazwa": message.author.display_name,
        "pytanie": tresc,
        "obrazek": obrazek,
        "kanal_id": message.channel.id,
        "message_id": 0,
    }
    save_config()

    try:
        await message.delete()
    except (discord.Forbidden, discord.NotFound):
        pass

    linie = [f"**Pytanie od: {message.author.display_name}**", "",
             tresc or "*(zdjęcie)*", "", "*Zagłosuj reakcją ✅ (Tak) lub ❌ (Nie) niżej!*",
             f"*#{ankieta_id}*"]
    opis = "\n".join(linie)
    wiadomosc = await message.channel.send(view=PanelView("Ankiety", opis, "ankiety", obrazek_url=obrazek))
    for reakcja in ("✅", "❌"):
        try:
            await wiadomosc.add_reaction(reakcja)
        except discord.HTTPException:
            pass

    CONFIG["ankiety_dane"][ankieta_id]["message_id"] = wiadomosc.id
    save_config()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    kanal_propozycje = CONFIG["kanaly"].get("propozycje")
    if kanal_propozycje and message.channel.id == kanal_propozycje:
        await obsluz_wiadomosc_propozycji(message)
        return

    kanal_ankiety = CONFIG["kanaly"].get("ankiety")
    if kanal_ankiety and message.channel.id == kanal_ankiety:
        await obsluz_wiadomosc_ankiety(message)
        return


ankieta_group = app_commands.Group(name="ankieta", description="Zarządzanie ankietami")


@ankieta_group.command(name="usun", description="Usuwa ankietę")
async def ankieta_usun(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["ankiety_dane"].pop(id, None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono ankiety o takim ID.", ephemeral=True)
        return
    save_config()
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await interaction.response.send_message(f"✅ Usunięto ankietę **#{id}**.", ephemeral=True)


# ========================
#   CENTRUM POMOCY (FAQ) - odpowiedzi mogą zawierać zdjęcie
# ========================

class CentrumPomocySelect(discord.ui.Select):
    def __init__(self):
        opcje = [discord.SelectOption(label=w["pytanie"][:100], value=w["id"]) for w in CONFIG["faq"][:25]]
        if not opcje:
            opcje = [discord.SelectOption(label="Brak pytań — wróć później", value="brak")]
        super().__init__(placeholder="Wybierz temat, w którym potrzebujesz pomocy...",
                          options=opcje, custom_id="igrzyskamc:pomoc:select")

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "brak":
            await interaction.response.send_message("⚠️ Centrum Pomocy jest jeszcze puste.", ephemeral=True)
            return
        wpis = next((w for w in CONFIG["faq"] if w["id"] == self.values[0]), None)
        if not wpis:
            await interaction.response.send_message("⚠️ Nie znaleziono tego wpisu (mógł zostać usunięty).", ephemeral=True)
            return
        opis = f"**{wpis['pytanie']}**\n\n{wpis['odpowiedz']}"
        await interaction.response.send_message(
            view=PanelView("Centrum Pomocy", opis, "pomoc", obrazek_url=wpis.get("obrazek") or None),
            ephemeral=True)


class CentrumPomocyPanel(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        opis = ("Masz pytanie? Wybierz temat z listy niżej, a od razu dostaniesz odpowiedź - "
                "zanim zrobisz ticket, sprawdź może jest tu już gotowa odpowiedź!")
        dzieci = [header_text("Centrum Pomocy"), discord.ui.Separator(),
                  discord.ui.TextDisplay(cytuj(opis)), discord.ui.Separator(),
                  discord.ui.ActionRow(CentrumPomocySelect()),
                  discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                  discord.ui.TextDisplay(footer_line("Centrum Pomocy"))]
        self.container = discord.ui.Container(*dzieci, accent_color=get_kolor("pomoc"))
        self.add_item(self.container)


centrumpomocy_group = app_commands.Group(name="centrumpomocy", description="Centrum Pomocy (FAQ)")


@centrumpomocy_group.command(name="dodaj", description="Dodaje wpis do Centrum Pomocy")
@app_commands.describe(obrazek="Opcjonalnie: link do zdjęcia dołączonego do odpowiedzi")
async def cp_dodaj(interaction: discord.Interaction, pytanie: str, odpowiedz: str, obrazek: Optional[str] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    nowy_id = nastepne_id("faq")
    CONFIG["faq"].append({"id": nowy_id, "pytanie": pytanie, "odpowiedz": odpowiedz, "obrazek": obrazek or ""})
    save_config()
    await interaction.response.send_message(f"✅ Dodano wpis **#{nowy_id}**. Odśwież panel (`/centrumpomocy panel`), żeby pojawił się na liście.", ephemeral=True)


@centrumpomocy_group.command(name="edytuj", description="Edytuje wpis w Centrum Pomocy")
@app_commands.describe(obrazek="Opcjonalnie: nowy link do zdjęcia (zostaw puste, by nie zmieniać)")
async def cp_edytuj(interaction: discord.Interaction, id: str, pytanie: str, odpowiedz: str, obrazek: Optional[str] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = next((w for w in CONFIG["faq"] if w["id"] == id), None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono wpisu o takim ID.", ephemeral=True)
        return
    wpis["pytanie"] = pytanie
    wpis["odpowiedz"] = odpowiedz
    if obrazek is not None:
        wpis["obrazek"] = obrazek
    save_config()
    await interaction.response.send_message(f"✅ Zaktualizowano wpis **#{id}**.", ephemeral=True)


@centrumpomocy_group.command(name="usun", description="Usuwa wpis z Centrum Pomocy")
async def cp_usun(interaction: discord.Interaction, id: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    przed = len(CONFIG["faq"])
    CONFIG["faq"] = [w for w in CONFIG["faq"] if w["id"] != id]
    if len(CONFIG["faq"]) == przed:
        await interaction.response.send_message("⚠️ Nie znaleziono wpisu o takim ID.", ephemeral=True)
        return
    save_config()
    await interaction.response.send_message(f"✅ Usunięto wpis **#{id}**.", ephemeral=True)


@centrumpomocy_group.command(name="lista", description="Wyświetla wszystkie wpisy Centrum Pomocy")
async def cp_lista(interaction: discord.Interaction):
    if not CONFIG["faq"]:
        await interaction.response.send_message("📋 Centrum Pomocy jest jeszcze puste.", ephemeral=True)
        return
    linie = [f"**#{w['id']}** — {w['pytanie']}" for w in CONFIG["faq"]]
    await interaction.response.send_message("\n".join(linie)[:1900], ephemeral=True)


@centrumpomocy_group.command(name="panel", description="Wysyła panel Centrum Pomocy na wskazany kanał")
async def cp_panel(interaction: discord.Interaction, kanal: Optional[discord.TextChannel] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("centrum_pomocy")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
    await docelowy.send(view=CentrumPomocyPanel())
    await interaction.response.send_message(f"✅ Panel Centrum Pomocy wysłany na {docelowy.mention}.", ephemeral=True)


@centrumpomocy_group.command(name="zasady", description="Wysyła informacje/zasady dot. Centrum Pomocy (godziny, regulamin, dozwolone programy)")
@app_commands.describe(
    godziny="Godziny działania Centrum Pomocy, np. 14.00-23.00",
    kanal_tickety="Kanał ticketów, który ma zostać wspomniany na końcu wiadomości",
    zasady="Opcjonalnie: własna lista zasad, każda linijka = jedna zasada (nadpisuje domyślne)",
    programy="Opcjonalnie: własna lista dozwolonych programów, każda linijka = jeden link (nadpisuje domyślne)",
    kanal="Kanał docelowy (domyślnie ten, na którym wpisujesz komendę)",
)
async def cp_zasady(interaction: discord.Interaction, godziny: str = "14.00-23.00",
                     kanal_tickety: Optional[discord.TextChannel] = None,
                     zasady: Optional[str] = None, programy: Optional[str] = None,
                     kanal: Optional[discord.TextChannel] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return

    docelowy = kanal or interaction.channel

    lista_zasad = [z.strip() for z in zasady.split("\n") if z.strip()] if zasady else [
        "**Zakaz** pingowania administracji",
        "Bezsensowne tickety będą skutkować **przerwą** lub **banem**",
        "Jeżeli gracz nie odpisuje na ticketa, zostaje on **zamknięty**",
        "Jeżeli gracz stworzy pustego ticketa zostanie on **usunięty**",
    ]
    lista_programow = [p.strip() for p in programy.split("\n") if p.strip()] if programy else [
        "https://www.nirsoft.net/utils/computer_activity_view.html",
        "https://www.nirsoft.net/utils/win_prefetch_view.html",
    ]

    zasady_tekst = "\n".join(f"{i}. {z}" for i, z in enumerate(lista_zasad, start=1))
    programy_tekst = "\n".join(f"{i}. {p}" for i, p in enumerate(lista_programow, start=1))
    tickety_wzmianka = kanal_tickety.mention if kanal_tickety else "kanale ticketów"

    opis = (
        f"**Centrum pomocy działa w godzinach {godziny}**\n\n"
        f"**Zasady centrum pomocy**\n{zasady_tekst}\n\n"
        f"**Programy które są dozwolone podczas sprawdzania:**\n{programy_tekst}\n\n"
        f"Jeżeli administrator poprosi was o pobranie innego programu, należy zgłosić to na {tickety_wzmianka}"
    )

    await docelowy.send(view=PanelView("Informacje o Centrum Pomocy", opis, "pomoc"))
    await interaction.response.send_message(f"✅ Wysłano zasady Centrum Pomocy na {docelowy.mention}.", ephemeral=True)


# ========================
#   TICKETY (ze zdjęciami - załączniki działają w kanale ticketu jak w każdej
#   zwykłej rozmowie na Discordzie, nie trzeba nic dodatkowo klikać)
# ========================

TICKET_KATEGORIE = ["Pomoc techniczna", "Zgłoszenie gracza", "Współpraca / Biznes", "Inne"]


class ZamknijTicketButton(discord.ui.Button):
    def __init__(self, numer: str, disabled: bool = False):
        super().__init__(label="Zamknij ticket", emoji="🔒", style=discord.ButtonStyle.danger,
                          custom_id=f"igrzyskamc:ticket:zamknij:{numer}", disabled=disabled)
        self.numer = numer

    async def callback(self, interaction: discord.Interaction):
        wpis = CONFIG["tickety_dane"].get(self.numer)
        if not wpis or wpis.get("zamkniety"):
            await interaction.response.send_message("⚠️ Ten ticket jest już zamknięty.", ephemeral=True)
            return

        await interaction.response.send_message("🔒 Zamykanie ticketu za 5 sekund... Zapisuję transkrypt.")

        linie = []
        async for wiadomosc in interaction.channel.history(limit=500, oldest_first=True):
            czas = wiadomosc.created_at.strftime("%Y-%m-%d %H:%M")
            tresc = wiadomosc.content or "[embed / załącznik]"
            linie.append(f"[{czas}] {wiadomosc.author}: {tresc}")
        transkrypt = "\n".join(linie) or "(brak wiadomości)"

        wpis["zamkniety"] = True
        save_config()

        log_id = CONFIG["kanaly"].get("tickety_log")
        if log_id:
            log_kanal = interaction.guild.get_channel(log_id)
            if log_kanal:
                plik = discord.File(io.BytesIO(transkrypt.encode("utf-8")), filename=f"ticket-{self.numer}.txt")
                opis = (f"Kategoria: {wpis['kategoria']}\nAutor: <@{wpis['autor_id']}>\n"
                        f"Zamknął: {interaction.user.mention}")
                await log_kanal.send(view=PanelView(f"Ticket #{self.numer} — Zamknięty", opis, "tickety"), file=plik)

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except (discord.NotFound, discord.Forbidden):
            pass


def build_ticket_panel(numer: str, kategoria: str, autor_id: int, zamkniety: bool = False) -> PanelView:
    opis = (f"Witaj <@{autor_id}>! Opisz swój problem, a nasz zespół odezwie się najszybciej jak to możliwe.\n\n"
            f"» Zanim napiszesz, sprawdź może odpowiedź jest już w Centrum Pomocy!\n"
            f"» Możesz tu spokojnie wysyłać zdjęcia - po prostu dodaj załącznik do wiadomości.")
    return PanelView(f"Ticket #{numer} — {kategoria}", opis, "tickety",
                      items=[ZamknijTicketButton(numer, disabled=zamkniety)])


class TicketySelect(discord.ui.Select):
    def __init__(self):
        opcje = [discord.SelectOption(label=k, emoji="🎫") for k in TICKET_KATEGORIE]
        super().__init__(placeholder="Wybierz kategorię ticketu...", options=opcje,
                          custom_id="igrzyskamc:tickety:select")

    async def callback(self, interaction: discord.Interaction):
        kategoria = self.values[0]
        gildia = interaction.guild
        numer = nastepne_id("ticket")

        kategoria_id = CONFIG["kanaly"].get("tickety_kategoria")
        kategoria_obiekt = gildia.get_channel(kategoria_id) if kategoria_id else None

        przeciazenia = {
            gildia.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                            attach_files=True, read_message_history=True),
            gildia.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        staff_id = CONFIG["role"].get("staff")
        if staff_id:
            staff_rola = gildia.get_role(staff_id)
            if staff_rola:
                przeciazenia[staff_rola] = discord.PermissionOverwrite(view_channel=True, send_messages=True,
                                                                        attach_files=True, read_message_history=True)

        try:
            kanal = await gildia.create_text_channel(
                name=f"ticket-{numer}", category=kategoria_obiekt, overwrites=przeciazenia,
                topic=f"Ticket #{numer} • {kategoria} • Właściciel: {interaction.user.id}",
            )
        except discord.Forbidden:
            await interaction.response.send_message("⚠️ Bot nie ma uprawnień do tworzenia kanałów.", ephemeral=True)
            return

        CONFIG["tickety_dane"][numer] = {
            "autor_id": interaction.user.id, "kategoria": kategoria, "kanal_id": kanal.id, "zamkniety": False,
        }
        save_config()

        widok = build_ticket_panel(numer, kategoria, interaction.user.id)
        await kanal.send(content=interaction.user.mention, view=widok)
        bot.add_view(widok)
        await interaction.response.send_message(f"✅ Utworzono ticket: {kanal.mention}", ephemeral=True)


class TicketyPanel(discord.ui.LayoutView):
    def __init__(self):
        super().__init__(timeout=None)
        opis = ("Potrzebujesz pomocy? Wybierz kategorię z listy niżej, a utworzymy dla Ciebie prywatny "
                "kanał widoczny tylko dla Ciebie i naszego zespołu. W ticketach możesz swobodnie wysyłać "
                "zdjęcia i pliki.")
        dzieci = [header_text("Centrum Ticketów"), discord.ui.Separator(),
                  discord.ui.TextDisplay(cytuj(opis)), discord.ui.Separator(),
                  discord.ui.ActionRow(TicketySelect()),
                  discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                  discord.ui.TextDisplay(footer_line("Centrum Ticketów"))]
        self.container = discord.ui.Container(*dzieci, accent_color=get_kolor("tickety"))
        self.add_item(self.container)


tickety_group = app_commands.Group(name="tickety", description="System ticketów")


@tickety_group.command(name="panel", description="Wysyła panel ticketów na wskazany kanał")
async def tickety_panel_cmd(interaction: discord.Interaction, kanal: Optional[discord.TextChannel] = None):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("tickety_panel")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
    await docelowy.send(view=TicketyPanel())
    await interaction.response.send_message(f"✅ Panel ticketów wysłany na {docelowy.mention}.", ephemeral=True)


# ========================
#   POWITANIA
# ========================

@bot.event
async def on_member_join(member: discord.Member):
    kanal_id = CONFIG["kanaly"].get("powitania")
    if not kanal_id:
        return
    kanal = member.guild.get_channel(kanal_id)
    if not kanal:
        return
    ilosc = member.guild.member_count
    tresc = CONFIG.get("powitanie_tresc", "Witaj {mention}!").format_map(
        SafeDict(mention=member.mention, ilosc=ilosc, nazwa=member.display_name))
    obrazek = CONFIG["obrazki"].get("powitanie") or None
    view = PanelView("Powitanie", tresc, "powitanie", obrazek_url=obrazek)
    try:
        await kanal.send(content=member.mention, view=view)
    except (discord.Forbidden, discord.HTTPException):
        pass


# ========================
#   KONKURSY (GIVEAWAY'E)
# ========================

def konkurs_wpis(konkurs_id: str) -> Optional[dict]:
    return CONFIG["konkursy_dane"].get(konkurs_id)


class DolaczKonkursButton(discord.ui.Button):
    def __init__(self, konkurs_id: str, disabled: bool = False):
        super().__init__(label="Kliknij, aby dołączyć do konkursu!", style=discord.ButtonStyle.success,
                          emoji="🎉", custom_id=f"igrzyskamc:konkurs:dolacz:{konkurs_id}", disabled=disabled)
        self.konkurs_id = konkurs_id

    async def callback(self, interaction: discord.Interaction):
        wpis = konkurs_wpis(self.konkurs_id)
        if not wpis or wpis.get("zakonczony"):
            await interaction.response.send_message("⚠️ Ten konkurs już się zakończył.", ephemeral=True)
            return

        rola_id = wpis.get("wymagana_rola")
        if rola_id:
            rola = interaction.guild.get_role(rola_id)
            if rola and rola not in interaction.user.roles:
                await interaction.response.send_message(
                    f"⚠️ Aby dołączyć do tego konkursu, musisz posiadać rolę {rola.mention}.", ephemeral=True)
                return

        uczestnicy = wpis.setdefault("uczestnicy", [])
        if interaction.user.id in uczestnicy:
            uczestnicy.remove(interaction.user.id)
            save_config()
            await interaction.response.send_message("↩️ Zrezygnowałeś/aś z udziału w konkursie.", ephemeral=True)
        else:
            uczestnicy.append(interaction.user.id)
            save_config()
            await interaction.response.send_message("🎉 Dołączono do konkursu! Powodzenia!", ephemeral=True)

        try:
            kanal = interaction.guild.get_channel(wpis["kanal_id"])
            wiadomosc = await kanal.fetch_message(wpis["message_id"])
            await wiadomosc.edit(view=build_konkurs_panel(self.konkurs_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
            pass


class UczestnicyKonkursButton(discord.ui.Button):
    """Nieklikalny przycisk-licznik pokazujący liczbę uczestników."""

    def __init__(self, konkurs_id: str, ilosc: int):
        super().__init__(label=f"W konkursie wzięło udział {ilosc} {forma_osob(ilosc)}!",
                          style=discord.ButtonStyle.secondary, emoji="👥",
                          custom_id=f"igrzyskamc:konkurs:licznik:{konkurs_id}", disabled=True)


def build_konkurs_panel(konkurs_id: str) -> PanelView:
    wpis = konkurs_wpis(konkurs_id)
    ilosc_uczestnikow = len(wpis.get("uczestnicy", []))
    koniec_ts = int(wpis["koniec"])
    zakonczony = wpis.get("zakonczony", False)

    linie = [
        f"🎁 **Nagrodą w konkursie jest:** `{wpis['nagroda']}`",
        f"👤 **Nagrodę może wygrać:** `{wpis['ilosc_zwyciezcow']} {forma_osob(wpis['ilosc_zwyciezcow'])}`",
    ]
    if zakonczony:
        linie.append(f"🏛️ **Zakończono:** <t:{koniec_ts}:R> (<t:{koniec_ts}:F>)")
    else:
        linie.append(f"🏛️ **Koniec:** <t:{koniec_ts}:R> (<t:{koniec_ts}:F>)")
    if wpis.get("wymagania"):
        linie.append(f"» **Wymagania:** `{wpis['wymagania']}`")
    if wpis.get("wymagana_rola"):
        linie.append(f"🔒 **Wymagana rola:** <@&{wpis['wymagana_rola']}>")
    linie.append(f"🧑‍🎤 **Organizator:** <@{wpis['host_id']}>")

    if zakonczony:
        zwyciezcy = wpis.get("zwyciezcy", [])
        if zwyciezcy:
            wzmianki = ", ".join(f"<@{uid}>" for uid in zwyciezcy)
            linie.append(f"\n🏆 **Zwycięzca(y):** {wzmianki}")
        else:
            linie.append("\n🏆 **Zwycięzcy:** Brak (za mało uczestników).")

    opis = "\n".join(linie)

    dolacz = DolaczKonkursButton(konkurs_id, disabled=zakonczony)
    licznik = UczestnicyKonkursButton(konkurs_id, ilosc_uczestnikow)
    obrazek = CONFIG["obrazki"].get("konkursy") or None

    return PanelView("Konkurs", opis, "konkursy", items=[dolacz, licznik], obrazek_url=obrazek)


async def wylosuj_zwyciezcow(wpis: dict) -> List[int]:
    uczestnicy = list(wpis.get("uczestnicy", []))
    ile = min(wpis.get("ilosc_zwyciezcow", 1), len(uczestnicy))
    if ile <= 0:
        return []
    return random.sample(uczestnicy, ile)


async def zakoncz_konkurs(bot_instance: commands.Bot, konkurs_id: str, reroll: bool = False):
    wpis = konkurs_wpis(konkurs_id)
    if not wpis:
        return None

    zwyciezcy = await wylosuj_zwyciezcow(wpis)
    wpis["zwyciezcy"] = zwyciezcy
    wpis["zakonczony"] = True
    save_config()

    kanal = bot_instance.get_channel(wpis["kanal_id"])
    if kanal:
        try:
            wiadomosc = await kanal.fetch_message(wpis["message_id"])
            await wiadomosc.edit(view=build_konkurs_panel(konkurs_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

        if zwyciezcy:
            wzmianki = ", ".join(f"<@{uid}>" for uid in zwyciezcy)
            naglowek = "🔄 Wylosowano ponownie" if reroll else "🎊 Konkurs zakończony"
            tresc = (f"» **{naglowek}!** Gratulacje {wzmianki} — wygrywasz(cie) **{wpis['nagroda']}**!\n"
                     f"» Skontaktuj się z organizatorem <@{wpis['host_id']}>, aby odebrać nagrodę.")
            await wyslij_karte(kanal, "Konkurs — Wyniki", tresc, "konkursy")
        else:
            await wyslij_karte(kanal, "Konkurs — Wyniki",
                                f"» Konkurs na **{wpis['nagroda']}** zakończył się bez zwycięzców "
                                f"— za mało uczestników.", "bledy")
    return zwyciezcy


@tasks.loop(seconds=30)
async def sprawdzaj_konkursy():
    teraz = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for konkurs_id, wpis in list(CONFIG["konkursy_dane"].items()):
        if not wpis.get("zakonczony") and wpis.get("koniec", 0) <= teraz:
            await zakoncz_konkurs(bot, konkurs_id)


konkurs_group = app_commands.Group(name="konkurs", description="Zarządzanie konkursami (giveaway'ami)")


@konkurs_group.command(name="stworz", description="Tworzy nowy konkurs")
@app_commands.describe(
    nagroda="Co można wygrać, np. Ranga VIP",
    zwyciezcy="Ile osób wygra konkurs",
    czas="Czas trwania, np. 1d, 12h, 30m, 1d12h",
    kanal="Kanał, na który wysłać konkurs (domyślnie ustawiony w /konfiguracja kanal)",
    wymagania="Opcjonalny opis wymagań (informacyjny), np. 'zaproś 1 osobę'",
    wymagana_rola="Opcjonalna rola wymagana, aby dołączyć",
)
async def konkurs_stworz(interaction: discord.Interaction, nagroda: str, zwyciezcy: int, czas: str,
                          kanal: Optional[discord.TextChannel] = None, wymagania: Optional[str] = None,
                          wymagana_rola: Optional[discord.Role] = None):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    if zwyciezcy < 1:
        await interaction.response.send_message("⚠️ Liczba zwycięzców musi wynosić co najmniej 1.", ephemeral=True)
        return

    delta = parsuj_czas(czas)
    if not delta:
        await interaction.response.send_message(
            "⚠️ Zły format czasu. Użyj np. `1d`, `12h`, `30m`, `1d12h30m`.", ephemeral=True)
        return

    docelowy_kanal = kanal
    if docelowy_kanal is None:
        kanal_id = CONFIG["kanaly"].get("konkursy")
        docelowy_kanal = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel
    if docelowy_kanal is None:
        await interaction.response.send_message("⚠️ Nie udało się ustalić kanału konkursu.", ephemeral=True)
        return

    koniec = datetime.datetime.now(datetime.timezone.utc) + delta
    konkurs_id = nastepne_id("konkurs")

    CONFIG["konkursy_dane"][konkurs_id] = {
        "nagroda": nagroda,
        "ilosc_zwyciezcow": zwyciezcy,
        "koniec": koniec.timestamp(),
        "wymagania": wymagania or "",
        "wymagana_rola": wymagana_rola.id if wymagana_rola else 0,
        "host_id": interaction.user.id,
        "kanal_id": docelowy_kanal.id,
        "message_id": 0,
        "uczestnicy": [],
        "zakonczony": False,
        "zwyciezcy": [],
    }
    save_config()

    wiadomosc = await docelowy_kanal.send(view=build_konkurs_panel(konkurs_id))
    CONFIG["konkursy_dane"][konkurs_id]["message_id"] = wiadomosc.id
    save_config()
    bot.add_view(build_konkurs_panel(konkurs_id), message_id=wiadomosc.id)

    await interaction.response.send_message(
        f"✅ Utworzono konkurs **#{konkurs_id}** na {docelowy_kanal.mention}.", ephemeral=True)


@konkurs_group.command(name="zakoncz", description="Kończy konkurs przed czasem i losuje zwycięzców")
@app_commands.describe(id="ID konkursu (widoczne w /konkurs lista)")
async def konkurs_zakoncz(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = konkurs_wpis(id)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono konkursu o takim ID.", ephemeral=True)
        return
    if wpis.get("zakonczony"):
        await interaction.response.send_message("⚠️ Ten konkurs już się zakończył.", ephemeral=True)
        return
    await interaction.response.send_message(f"✅ Kończenie konkursu **#{id}**...", ephemeral=True)
    await zakoncz_konkurs(bot, id)


@konkurs_group.command(name="reroll", description="Losuje nowych zwycięzców zakończonego konkursu")
@app_commands.describe(id="ID konkursu (widoczne w /konkurs lista)")
async def konkurs_reroll(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = konkurs_wpis(id)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono konkursu o takim ID.", ephemeral=True)
        return
    if not wpis.get("zakonczony"):
        await interaction.response.send_message("⚠️ Ten konkurs jeszcze się nie zakończył.", ephemeral=True)
        return
    await interaction.response.send_message(f"🔄 Losowanie ponowne konkursu **#{id}**...", ephemeral=True)
    await zakoncz_konkurs(bot, id, reroll=True)


@konkurs_group.command(name="usun", description="Usuwa konkurs bez losowania zwycięzców")
@app_commands.describe(id="ID konkursu (widoczne w /konkurs lista)")
async def konkurs_usun(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["konkursy_dane"].pop(id, None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono konkursu o takim ID.", ephemeral=True)
        return
    save_config()
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await interaction.response.send_message(f"✅ Usunięto konkurs **#{id}**.", ephemeral=True)


@konkurs_group.command(name="lista", description="Wyświetla listę aktywnych konkursów")
async def konkurs_lista(interaction: discord.Interaction):
    aktywne = {k: v for k, v in CONFIG["konkursy_dane"].items() if not v.get("zakonczony")}
    if not aktywne:
        await interaction.response.send_message("📋 Brak aktywnych konkursów.", ephemeral=True)
        return
    linie = []
    for konkurs_id, wpis in aktywne.items():
        linie.append(f"**#{konkurs_id}** — `{wpis['nagroda']}` — <t:{int(wpis['koniec'])}:R> — "
                      f"{len(wpis.get('uczestnicy', []))} {forma_osob(len(wpis.get('uczestnicy', [])))}")
    await interaction.response.send_message(view=PanelView("Aktywne Konkursy", "\n".join(linie)[:3900], "konkursy"), ephemeral=True)


# ========================
#   OGŁOSZENIA (styl changelogu - klasyczny embed, tak jak w bocie-wzorze)
# ========================

ogloszenie_group = app_commands.Group(name="ogloszenie", description="Wysyła / edytuje / usuwa ogłoszenie w stylu changelogu")


def build_ogloszenie_embed(tytul: str, tresc: str) -> discord.Embed:
    punkty = "\n".join(f"• {linia.strip()}" for linia in tresc.split("\\n") if linia.strip())
    return karta(tytul, punkty, CONFIG["kolory"]["info"])


@ogloszenie_group.command(name="wyslij", description="Wysyła ogłoszenie w stylu changelogu")
@app_commands.describe(tytul="Tytuł, np. 'ChestPvP | Nowość'", tresc="Treść (użyj \\n dla nowej linijki / punktu)")
async def ogloszenie_wyslij(interaction: discord.Interaction, tytul: str, tresc: str,
                             kanal: Optional[discord.TextChannel] = None):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("ogloszenia")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel

    embed = build_ogloszenie_embed(tytul, tresc)
    wiadomosc = await docelowy.send(embed=embed)

    ogloszenie_id = nastepne_id("ogloszenie")
    CONFIG["ogloszenia_dane"][ogloszenie_id] = {
        "kanal_id": docelowy.id, "message_id": wiadomosc.id, "tytul": tytul, "tresc": tresc,
    }
    save_config()

    await interaction.response.send_message(f"✅ Ogłoszenie **#{ogloszenie_id}** wysłane na {docelowy.mention}.", ephemeral=True)


@ogloszenie_group.command(name="edytuj", description="Edytuje wcześniej wysłane ogłoszenie")
@app_commands.describe(id="ID ogłoszenia (widoczne w /ogloszenie lista)")
async def ogloszenie_edytuj(interaction: discord.Interaction, id: str, tytul: str, tresc: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["ogloszenia_dane"].get(id)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono ogłoszenia o takim ID.", ephemeral=True)
        return
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.edit(embed=build_ogloszenie_embed(tytul, tresc))
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        await interaction.response.send_message("⚠️ Nie udało się znaleźć/edytować oryginalnej wiadomości.", ephemeral=True)
        return
    wpis["tytul"] = tytul
    wpis["tresc"] = tresc
    save_config()
    await interaction.response.send_message(f"✅ Zaktualizowano ogłoszenie **#{id}**.", ephemeral=True)


@ogloszenie_group.command(name="usun", description="Usuwa wysłane ogłoszenie")
@app_commands.describe(id="ID ogłoszenia (widoczne w /ogloszenie lista)")
async def ogloszenie_usun(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = CONFIG["ogloszenia_dane"].pop(id, None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono ogłoszenia o takim ID.", ephemeral=True)
        return
    save_config()
    try:
        kanal = interaction.guild.get_channel(wpis["kanal_id"])
        wiadomosc = await kanal.fetch_message(wpis["message_id"])
        await wiadomosc.delete()
    except (discord.NotFound, discord.Forbidden, discord.HTTPException, AttributeError):
        pass
    await interaction.response.send_message(f"✅ Usunięto ogłoszenie **#{id}**.", ephemeral=True)


@ogloszenie_group.command(name="lista", description="Wyświetla listę wysłanych ogłoszeń")
async def ogloszenie_lista(interaction: discord.Interaction):
    if not CONFIG["ogloszenia_dane"]:
        await interaction.response.send_message("📋 Brak wysłanych ogłoszeń.", ephemeral=True)
        return
    linie = [f"**#{oid}** — {w['tytul']}" for oid, w in CONFIG["ogloszenia_dane"].items()]
    await interaction.response.send_message("\n".join(linie)[:1900], ephemeral=True)


# ========================
#   KONFIGURACJA
# ========================

konfiguracja_group = app_commands.Group(name="konfiguracja", description="Ustawienia bota")


@konfiguracja_group.command(name="nazwa", description="Ustawia nazwę wyświetlaną w nagłówkach i stopkach kart")
async def konfig_nazwa(interaction: discord.Interaction, nazwa: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["nazwa_serwera"] = nazwa
    save_config()
    await interaction.response.send_message(f"✅ Nazwa ustawiona na **{nazwa}**.", ephemeral=True)


@konfiguracja_group.command(name="kanal", description="Ustawia kanał używany przez bota")
@app_commands.choices(typ=[
    app_commands.Choice(name="Panel ticketów", value="tickety_panel"),
    app_commands.Choice(name="Log ticketów (transkrypty)", value="tickety_log"),
    app_commands.Choice(name="Centrum Pomocy", value="centrum_pomocy"),
    app_commands.Choice(name="Propozycje (auto-zamiana wiadomości!)", value="propozycje"),
    app_commands.Choice(name="Ankiety (auto-zamiana wiadomości!)", value="ankiety"),
    app_commands.Choice(name="Błędy", value="bledy"),
    app_commands.Choice(name="Ogłoszenia", value="ogloszenia"),
    app_commands.Choice(name="Powitania", value="powitania"),
    app_commands.Choice(name="Konkursy (domyślny kanał)", value="konkursy"),
])
async def konfig_kanal(interaction: discord.Interaction, typ: app_commands.Choice[str], kanal: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["kanaly"][typ.value] = kanal.id
    save_config()
    await interaction.response.send_message(f"✅ Kanał **{typ.name}** ustawiony na {kanal.mention}.", ephemeral=True)


@konfiguracja_group.command(name="kategoria-ticketow", description="Ustawia kategorię, w której tworzone są tickety")
async def konfig_kategoria(interaction: discord.Interaction, kategoria: discord.CategoryChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["kanaly"]["tickety_kategoria"] = kategoria.id
    save_config()
    await interaction.response.send_message(f"✅ Kategoria ticketów ustawiona na **{kategoria.name}**.", ephemeral=True)


@konfiguracja_group.command(name="rola", description="Ustawia rolę używaną przez bota")
@app_commands.choices(typ=[
    app_commands.Choice(name="Staff", value="staff"),
    app_commands.Choice(name="Powiadomienia - Propozycje", value="powiadomienia_propozycje"),
    app_commands.Choice(name="Powiadomienia - Błędy", value="powiadomienia_bledy"),
])
async def konfig_rola(interaction: discord.Interaction, typ: app_commands.Choice[str], rola: discord.Role):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["role"][typ.value] = rola.id
    save_config()
    await interaction.response.send_message(f"✅ Rola **{typ.name}** ustawiona na {rola.mention}.", ephemeral=True)


@konfiguracja_group.command(name="kolor", description="Zmienia kolor karty danej sekcji")
@app_commands.describe(hex="Kolor w formacie HEX, np. #5865F2")
@app_commands.choices(sekcja=[
    app_commands.Choice(name="Propozycje", value="propozycje"),
    app_commands.Choice(name="Błędy", value="bledy"),
    app_commands.Choice(name="Info / Ogłoszenia", value="info"),
    app_commands.Choice(name="Ankiety", value="ankiety"),
    app_commands.Choice(name="Pomoc / Centrum Pomocy", value="pomoc"),
    app_commands.Choice(name="Tickety", value="tickety"),
    app_commands.Choice(name="Powitania", value="powitanie"),
    app_commands.Choice(name="Konkursy", value="konkursy"),
])
async def konfig_kolor(interaction: discord.Interaction, sekcja: app_commands.Choice[str], hex: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    try:
        wartosc = int(hex.lstrip("#"), 16)
    except ValueError:
        await interaction.response.send_message("⚠️ Zły format koloru. Użyj np. `#5865F2`.", ephemeral=True)
        return
    CONFIG["kolory"][sekcja.value] = wartosc
    save_config()
    await interaction.response.send_message(f"✅ Kolor sekcji **{sekcja.name}** zmieniony.", ephemeral=True)


@konfiguracja_group.command(name="obrazek", description="Ustawia obrazek (link URL) dołączany do panelu")
@app_commands.choices(typ=[
    app_commands.Choice(name="Powitania", value="powitanie"),
    app_commands.Choice(name="Konkursy", value="konkursy"),
])
@app_commands.describe(url="Link do zdjęcia (zostaw puste / wpisz 'brak', aby usunąć)")
async def konfig_obrazek(interaction: discord.Interaction, typ: app_commands.Choice[str], url: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["obrazki"][typ.value] = "" if url.lower() in ("brak", "-", "") else url
    save_config()
    await interaction.response.send_message(f"✅ Obrazek sekcji **{typ.name}** zaktualizowany.", ephemeral=True)


@konfiguracja_group.command(name="powitanie", description="Ustawia treść wiadomości powitalnej (możesz użyć {mention} i {ilosc})")
async def konfig_powitanie(interaction: discord.Interaction, tresc: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    CONFIG["powitanie_tresc"] = tresc
    save_config()
    await interaction.response.send_message("✅ Treść powitania zaktualizowana.", ephemeral=True)


# ========================
#   /pomoc  — panel ze wszystkimi komendami bota
# ========================

POMOC_KATEGORIE = {
    "ogolne": {
        "etykieta": "🧭 Ogólne",
        "tresc": (
            "Witaj w panelu pomocy bota **{nazwa}**! Wybierz kategorię z listy niżej, żeby "
            "zobaczyć dostępne komendy.\n\n"
            "`/pomoc` — Pokazuje ten panel.\n\n"
            "Zacznij od zakładki **⚙️ Konfiguracja**, jeśli dopiero ustawiasz bota od zera."
        ),
    },
    "tickety": {
        "etykieta": "🎫 Tickety",
        "tresc": (
            "`/tickety panel [kanal]` — Wysyła panel z wyborem kategorii ticketu. *(Admin)*\n\n"
            "Ticket tworzy się automatycznie po wybraniu kategorii przez gracza — prywatny kanał "
            "widoczny tylko dla autora i roli Staff. Można w nim swobodnie wysyłać zdjęcia.\n\n"
            "Przycisk **🔒 Zamknij ticket** zapisuje transkrypt (jeśli ustawiono kanał logów) i "
            "usuwa kanał po 5 sekundach."
        ),
    },
    "centrum_pomocy": {
        "etykieta": "❓ Centrum Pomocy",
        "tresc": (
            "`/centrumpomocy dodaj <pytanie> <odpowiedz> [obrazek]` — Dodaje wpis FAQ, opcjonalnie ze zdjęciem. *(Admin)*\n"
            "`/centrumpomocy edytuj <id> <pytanie> <odpowiedz> [obrazek]` — Edytuje wpis. *(Admin)*\n"
            "`/centrumpomocy usun <id>` — Usuwa wpis. *(Admin)*\n"
            "`/centrumpomocy lista` — Pokazuje wszystkie wpisy z ID.\n"
            "`/centrumpomocy panel [kanal]` — Wysyła panel z listą wyboru tematu. *(Admin)*\n"
            "`/centrumpomocy zasady` — Wysyła zasady Centrum Pomocy (godziny, regulamin, programy). *(Admin)*"
        ),
    },
    "propozycje": {
        "etykieta": "💡 Propozycje",
        "tresc": (
            "`/propozycje panel [kanal]` — Wysyła panel z przyciskiem 'Napisz swoją propozycję'. *(Admin)*\n"
            "`/propozycje status <id> <status>` — Zmienia status propozycji. *(Staff)*\n"
            "`/propozycje usun <id>` — Usuwa propozycję. *(Staff)*\n\n"
            "**Najprościej:** ustaw kanał propozycji w `/konfiguracja kanal` — każda wiadomość "
            "napisana tam (tekst i/lub zdjęcie) sama zamieni się w kartę propozycji z reakcjami 👍/👎. "
            "Przycisk z panelu robi to samo przez okienko (bez zdjęcia)."
        ),
    },
    "bledy": {
        "etykieta": "🐞 Błędy",
        "tresc": (
            "`/bledy panel [kanal]` — Wysyła panel z przyciskiem 'Zgłoś błąd'. *(Admin)*\n"
            "`/bledy status <id> <status>` — Zmienia status zgłoszenia. *(Staff)*\n"
            "`/bledy usun <id>` — Usuwa zgłoszenie. *(Staff)*"
        ),
    },
    "ankiety": {
        "etykieta": "📊 Ankiety",
        "tresc": (
            "`/ankieta usun <id>` — Usuwa ankietę. *(Staff)*\n\n"
            "**Najprościej:** ustaw kanał ankiet w `/konfiguracja kanal` — każda wiadomość napisana "
            "tam zamienia się w ankietę tak/nie. Liczbę głosów pokazują natywne reakcje ✅/❌ Discorda."
        ),
    },
    "ogloszenia": {
        "etykieta": "📢 Ogłoszenia",
        "tresc": (
            "`/ogloszenie wyslij <tytul> <tresc> [kanal]` — Wysyła ogłoszenie w stylu changelogu. "
            "W treści użyj `\\n`, żeby rozbić tekst na osobne punkty. *(Staff)*\n"
            "`/ogloszenie edytuj <id> <tytul> <tresc>` — Edytuje wysłane ogłoszenie. *(Staff)*\n"
            "`/ogloszenie usun <id>` — Usuwa wysłane ogłoszenie. *(Staff)*\n"
            "`/ogloszenie lista` — Pokazuje listę wysłanych ogłoszeń z ID."
        ),
    },
    "konkursy": {
        "etykieta": "🎉 Konkursy",
        "tresc": (
            "`/konkurs stworz <nagroda> <zwyciezcy> <czas> [kanal] [wymagania] [wymagana_rola]` — "
            "Tworzy nowy konkurs. *(Staff)*\n"
            "`/konkurs zakoncz <id>` — Kończy konkurs przed czasem i losuje zwycięzców. *(Staff)*\n"
            "`/konkurs reroll <id>` — Losuje nowych zwycięzców ponownie. *(Staff)*\n"
            "`/konkurs usun <id>` — Usuwa konkurs bez losowania. *(Staff)*\n"
            "`/konkurs lista` — Wyświetla listę aktywnych konkursów."
        ),
    },
    "powitania": {
        "etykieta": "👋 Powitania",
        "tresc": (
            "`/konfiguracja kanal Powitania <kanal>` — Ustawia kanał powitań. *(Admin)*\n"
            "`/konfiguracja powitanie <tresc>` — Ustawia treść (możesz użyć `{mention}` i `{ilosc}`). *(Admin)*\n"
            "`/konfiguracja obrazek Powitania <url>` — Ustawia obrazek dołączony do powitania. *(Admin)*\n\n"
            "Wiadomość wysyła się automatycznie, gdy ktoś dołączy do serwera."
        ),
    },
    "konfiguracja": {
        "etykieta": "⚙️ Konfiguracja",
        "tresc": (
            "`/konfiguracja nazwa <nazwa>` — Nazwa w nagłówkach i stopkach kart. *(Admin)*\n"
            "`/konfiguracja kanal <typ> <kanal>` — Kanał modułu (tickety, propozycje, ankiety, "
            "błędy, centrum pomocy, log ticketów, ogłoszenia, powitania, konkursy). *(Admin)*\n"
            "`/konfiguracja kategoria-ticketow <kategoria>` — Kategoria, w której tworzą się tickety. *(Admin)*\n"
            "`/konfiguracja rola <typ> <rola>` — Rola Staff / powiadomień. *(Admin)*\n"
            "`/konfiguracja kolor <sekcja> <hex>` — Kolor karty danej sekcji, np. `#5865F2`. *(Admin)*\n"
            "`/konfiguracja obrazek <typ> <url>` — Obrazek dla powitań/konkursów. *(Admin)*\n"
            "`/konfiguracja powitanie <tresc>` — Treść powitania. *(Admin)*"
        ),
    },
}


class PomocSelect(discord.ui.Select):
    def __init__(self, aktualna: str):
        opcje = [
            discord.SelectOption(label=dane["etykieta"], value=klucz, default=(klucz == aktualna))
            for klucz, dane in POMOC_KATEGORIE.items()
        ]
        super().__init__(placeholder="Wybierz kategorię komend...", options=opcje,
                          custom_id="igrzyskamc:pomoc:kategoria", min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.edit_message(view=PomocPanel(self.values[0]))


class PomocPanel(discord.ui.LayoutView):
    def __init__(self, kategoria: str = "ogolne"):
        super().__init__(timeout=300)
        dane = POMOC_KATEGORIE.get(kategoria, POMOC_KATEGORIE["ogolne"])
        nazwa = CONFIG.get("nazwa_serwera", "Bot")
        tresc = dane["tresc"].format_map(SafeDict(nazwa=nazwa))

        dzieci = [header_text(f"Pomoc — {dane['etykieta']}"), discord.ui.Separator(),
                  discord.ui.TextDisplay(cytuj(tresc)), discord.ui.Separator(),
                  discord.ui.ActionRow(PomocSelect(kategoria)),
                  discord.ui.Separator(spacing=discord.SeparatorSpacing.small),
                  discord.ui.TextDisplay(footer_line("Pomoc"))]
        self.container = discord.ui.Container(*dzieci, accent_color=get_kolor("pomoc"))
        self.add_item(self.container)


@bot.tree.command(name="pomoc", description="Pokazuje wszystkie dostępne komendy bota")
async def pomoc_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(view=PomocPanel(), ephemeral=True)


# ========================
#   START BOTA
# ========================

bot.tree.add_command(propozycje_group)
bot.tree.add_command(bledy_group)
bot.tree.add_command(centrumpomocy_group)
bot.tree.add_command(ankieta_group)
bot.tree.add_command(tickety_group)
bot.tree.add_command(konfiguracja_group)
bot.tree.add_command(ogloszenie_group)
bot.tree.add_command(konkurs_group)


@bot.event
async def on_ready():
    bot.add_view(ZgloszeniePanel("propozycja"))
    bot.add_view(ZgloszeniePanel("blad"))
    bot.add_view(CentrumPomocyPanel())
    bot.add_view(TicketyPanel())

    for numer, wpis in list(CONFIG["tickety_dane"].items()):
        if not wpis.get("zamkniety"):
            bot.add_view(build_ticket_panel(numer, wpis.get("kategoria", "Inne"), wpis.get("autor_id", 0)))

    teraz = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for konkurs_id, wpis in list(CONFIG["konkursy_dane"].items()):
        if not wpis.get("zakonczony"):
            if wpis.get("koniec", 0) <= teraz:
                await zakoncz_konkurs(bot, konkurs_id)
            elif wpis.get("message_id"):
                bot.add_view(build_konkurs_panel(konkurs_id), message_id=wpis["message_id"])

    if not sprawdzaj_konkursy.is_running():
        sprawdzaj_konkursy.start()

    if TEST_GUILD_ID:
        guild_obj = discord.Object(id=TEST_GUILD_ID)
        bot.tree.copy_global_to(guild=guild_obj)
        await bot.tree.sync(guild=guild_obj)
    else:
        await bot.tree.sync()

    print(f"Zalogowano jako {bot.user} — bot gotowy.")


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("Brak zmiennej środowiskowej DISCORD_TOKEN.")
    bot.run(token)
