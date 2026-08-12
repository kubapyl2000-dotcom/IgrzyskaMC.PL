"""
IgrzyskaMC.PL - Discord Bot
Moduły: Tickety, Centrum Pomocy, Ankiety, Propozycje, Błędy

Wymagane zmienne środowiskowe:
  DISCORD_TOKEN   - token bota
  TEST_GUILD_ID   - (opcjonalnie) ID serwera do natychmiastowej synchronizacji komend
"""

import os
import io
import json
import re
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
    },

    "role": {
        "staff": 0,
        "powiadomienia_propozycje": 0,
        "powiadomienia_bledy": 0,
        "tag_propozycje": 0,
        "tag_bledy": 0,
        "tag_centrum_pomocy": 0,
        "tag_ankiety": 0,
        "tag_ogloszenia": 0,
    },

    "liczniki": {"propozycja": 0, "blad": 0, "ankieta": 0, "ticket": 0, "faq": 0},

    "propozycje_dane": {},
    "bledy_dane": {},
    "ankiety_dane": {},
    "tickety_dane": {},
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


# ========================
#   BOT
# ========================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

TEST_GUILD_ID = int(os.getenv("TEST_GUILD_ID", "0"))


def is_admin(interaction: discord.Interaction) -> bool:
    return interaction.user.guild_permissions.administrator


def is_staff(interaction: discord.Interaction) -> bool:
    if interaction.user.guild_permissions.administrator:
        return True
    rola_id = CONFIG["role"].get("staff")
    if rola_id:
        rola = interaction.guild.get_role(rola_id)
        if rola and rola in interaction.user.roles:
            return True
    return False


# ========================
#   POMOCNICZE / DESIGN
# ========================

def nastepne_id(klucz: str) -> str:
    CONFIG["liczniki"][klucz] = CONFIG["liczniki"].get(klucz, 0) + 1
    save_config()
    return str(CONFIG["liczniki"][klucz])


def karta(tytul: str, opis: str, kolor: int, stopka: Optional[str] = None) -> discord.Embed:
    """Buduje standardową 'kartę' (embed) w stylu zamówionym przez klienta - kolorowy pasek,
    pogrubiony tytuł, treść, stopka z copyrightem i datą."""
    embed = discord.Embed(title=tytul, description=opis, color=kolor)
    nazwa = CONFIG.get("nazwa_serwera", "Bot")
    rok = datetime.datetime.now().year
    embed.set_footer(text=stopka or f"🎮 Copyright {nazwa} - {rok}")
    embed.timestamp = datetime.datetime.now(datetime.timezone.utc)
    return embed


async def wyslij_tag(kanal: discord.TextChannel, sekcja: str, rola_klucz: str):
    """Wysyła małą 'etykietkę' nad kartą. Jeśli ustawiono rolę-tag, użyje jej wzmianki
    (niebieska 'pigułka' bez realnego pingowania); w przeciwnym razie zwykły pogrubiony tekst."""
    rola_id = CONFIG["role"].get(rola_klucz)
    if rola_id:
        rola = kanal.guild.get_role(rola_id)
        if rola:
            await kanal.send(content=f"{rola.mention} • {sekcja}",
                              allowed_mentions=discord.AllowedMentions(roles=False))
            return
    await kanal.send(content=f"**• {sekcja}**")


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


# ========================
#   PROPOZYCJE i BŁĘDY (wspólny system "zgłoszeń")
# ========================

ZGLOSZENIA_TYPY = {
    "propozycja": {
        "nazwa": "Propozycja", "sekcja": "Propozycje", "kolor": "propozycje",
        "emoji_przycisku": "💡", "etykieta_przycisku": "Napisz swoją propozycję",
        "magazyn": "propozycje_dane", "rola_powiadomien": "powiadomienia_propozycje",
        "kanal": "propozycje", "tag_rola": "tag_propozycje",
        "status_startowy": "Rozpatrywana", "reakcje": ["👍", "👎"],
        "etykieta_tresc": "Treść propozycji", "stopka_dodatkowa": "Zagłosuj na tę propozycję za pomocą emotek niżej!",
    },
    "blad": {
        "nazwa": "Zgłoszenie błędu", "sekcja": "Błędy", "kolor": "bledy",
        "emoji_przycisku": "🐞", "etykieta_przycisku": "Zgłoś błąd",
        "magazyn": "bledy_dane", "rola_powiadomien": "powiadomienia_bledy",
        "kanal": "bledy", "tag_rola": "tag_bledy",
        "status_startowy": "Nowe zgłoszenie", "reakcje": [],
        "etykieta_tresc": "Opis błędu (co się dzieje, jak to odtworzyć)", "stopka_dodatkowa": None,
    },
}


class ZgloszenieModal(discord.ui.Modal):
    def __init__(self, typ: str):
        dane = ZGLOSZENIA_TYPY[typ]
        super().__init__(title=f"Nowe: {dane['nazwa']}")
        self.typ = typ
        self.tryb = discord.ui.TextInput(label="Na jaki tryb / serwer?", max_length=100, placeholder="np. SkyPvP")
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
            "kanal_id": kanal.id,
            "message_id": 0,
            "status": dane["status_startowy"],
        }
        save_config()

        await wyslij_tag(kanal, dane["sekcja"], dane["tag_rola"])
        embed = build_zgloszenie_embed(self.typ, wpis_id)
        wiadomosc = await kanal.send(embed=embed)
        for reakcja in dane["reakcje"]:
            await wiadomosc.add_reaction(reakcja)

        CONFIG[dane["magazyn"]][wpis_id]["message_id"] = wiadomosc.id
        save_config()

        rola_id = CONFIG["role"].get(dane["rola_powiadomien"])
        if rola_id:
            rola = interaction.guild.get_role(rola_id)
            if rola:
                await kanal.send(f"🔔 {rola.mention} — nowe zgłoszenie czeka!",
                                  allowed_mentions=discord.AllowedMentions(roles=True))

        await interaction.response.send_message(f"✅ {dane['nazwa']} **#{wpis_id}** została wysłana na {kanal.mention}!", ephemeral=True)


def build_zgloszenie_embed(typ: str, wpis_id: str) -> discord.Embed:
    dane = ZGLOSZENIA_TYPY[typ]
    wpis = CONFIG[dane["magazyn"]][wpis_id]
    tytul = f"{dane['nazwa']} od: {wpis['autor_nazwa']}, na tryb: {wpis['tryb']}"
    stopka = f"#{wpis_id} • Status: {wpis['status']}"
    if dane["stopka_dodatkowa"]:
        stopka = f"{dane['stopka_dodatkowa']} • {stopka}"
    return karta(tytul, wpis["tresc"], CONFIG["kolory"][dane["kolor"]], stopka=stopka)


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
            await wiadomosc.edit(embed=build_zgloszenie_embed(typ, wpis_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass
    return True


class ZgloszeniePanel(discord.ui.View):
    def __init__(self, typ: str):
        super().__init__(timeout=None)
        dane = ZGLOSZENIA_TYPY[typ]
        self.typ = typ

        przycisk_napisz = discord.ui.Button(label=dane["etykieta_przycisku"], emoji=dane["emoji_przycisku"],
                                             style=discord.ButtonStyle.primary,
                                             custom_id=f"igrzyskamc:zgloszenie:{typ}:napisz")
        przycisk_napisz.callback = self.napisz
        self.add_item(przycisk_napisz)

        przycisk_powiadom = discord.ui.Button(label="Powiadamiaj o nowych", emoji="🔔",
                                               style=discord.ButtonStyle.success,
                                               custom_id=f"igrzyskamc:zgloszenie:{typ}:powiadom")
        przycisk_powiadom.callback = self.powiadom
        self.add_item(przycisk_powiadom)

    async def napisz(self, interaction: discord.Interaction):
        await interaction.response.send_modal(ZgloszenieModal(self.typ))

    async def powiadom(self, interaction: discord.Interaction):
        dane = ZGLOSZENIA_TYPY[self.typ]
        rola_id = CONFIG["role"].get(dane["rola_powiadomien"])
        if not rola_id:
            await interaction.response.send_message("⚠️ Rola powiadomień nie jest jeszcze ustawiona przez administrację.", ephemeral=True)
            return
        rola = interaction.guild.get_role(rola_id)
        if rola in interaction.user.roles:
            await interaction.user.remove_roles(rola)
            await interaction.response.send_message("🔕 Wyłączono powiadomienia.", ephemeral=True)
        else:
            await interaction.user.add_roles(rola)
            await interaction.response.send_message("🔔 Włączono powiadomienia!", ephemeral=True)


propozycje_group = app_commands.Group(name="propozycje", description="System propozycji od graczy")
bledy_group = app_commands.Group(name="bledy", description="System zgłaszania błędów")


@propozycje_group.command(name="panel", description="Wysyła panel propozycji na wskazany kanał")
async def propozycje_panel(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    embed = karta("💡 Propozycje",
                   "Masz pomysł na zmianę w grze? Kliknij przycisk niżej i podziel się nim z nami!\n"
                   "Głosuj na propozycje innych, klikając 👍 lub 👎 pod każdym zgłoszeniem.",
                   CONFIG["kolory"]["propozycje"])
    await kanal.send(embed=embed, view=ZgloszeniePanel("propozycja"))
    await interaction.response.send_message(f"✅ Panel propozycji wysłany na {kanal.mention}.", ephemeral=True)


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


@bledy_group.command(name="panel", description="Wysyła panel zgłaszania błędów na wskazany kanał")
async def bledy_panel(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    embed = karta("🐞 Błędy",
                   "Znalazłeś błąd w grze lub na serwerze? Kliknij przycisk niżej i opisz co się dzieje — "
                   "im dokładniej, tym szybciej to naprawimy!",
                   CONFIG["kolory"]["bledy"])
    await kanal.send(embed=embed, view=ZgloszeniePanel("blad"))
    await interaction.response.send_message(f"✅ Panel błędów wysłany na {kanal.mention}.", ephemeral=True)


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
#   CENTRUM POMOCY (FAQ)
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
        embed = karta(f"❓ {wpis['pytanie']}", wpis["odpowiedz"], CONFIG["kolory"]["pomoc"])
        await interaction.response.send_message(embed=embed, ephemeral=True)


class CentrumPomocyPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(CentrumPomocySelect())


centrumpomocy_group = app_commands.Group(name="centrumpomocy", description="Centrum Pomocy (FAQ)")


@centrumpomocy_group.command(name="dodaj", description="Dodaje wpis do Centrum Pomocy")
async def cp_dodaj(interaction: discord.Interaction, pytanie: str, odpowiedz: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    nowy_id = nastepne_id("faq")
    CONFIG["faq"].append({"id": nowy_id, "pytanie": pytanie, "odpowiedz": odpowiedz})
    save_config()
    await interaction.response.send_message(f"✅ Dodano wpis **#{nowy_id}**. Odśwież panel (`/centrumpomocy panel`), żeby pojawił się na liście.", ephemeral=True)


@centrumpomocy_group.command(name="edytuj", description="Edytuje wpis w Centrum Pomocy")
async def cp_edytuj(interaction: discord.Interaction, id: str, pytanie: str, odpowiedz: str):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    wpis = next((w for w in CONFIG["faq"] if w["id"] == id), None)
    if not wpis:
        await interaction.response.send_message("⚠️ Nie znaleziono wpisu o takim ID.", ephemeral=True)
        return
    wpis["pytanie"] = pytanie
    wpis["odpowiedz"] = odpowiedz
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
async def cp_panel(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    embed = karta("❓ Centrum Pomocy",
                   "Masz pytanie? Wybierz temat z listy niżej, a od razu dostaniesz odpowiedź — "
                   "zanim zrobisz ticket, sprawdź może jest tu już gotowa odpowiedź!",
                   CONFIG["kolory"]["pomoc"])
    await wyslij_tag(kanal, "Centrum Pomocy", "tag_centrum_pomocy")
    await kanal.send(embed=embed, view=CentrumPomocyPanel())
    await interaction.response.send_message(f"✅ Panel Centrum Pomocy wysłany na {kanal.mention}.", ephemeral=True)


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

    tresc = (
        f"# Informacje odnośnie centrum pomocy\n"
        f"**Centrum pomocy działa w godzinach {godziny}**\n\n"
        f"> **Zasady centrum pomocy**\n\n"
        f"{zasady_tekst}\n\n"
        f"> **Programy które są dozwolone podczas sprawdzania:**\n\n"
        f"{programy_tekst}\n\n"
        f"Jeżeli administrator poprosi was o pobranie innego programu, należy zgłosić to na {tickety_wzmianka}"
    )

    await docelowy.send(tresc)
    await interaction.response.send_message(f"✅ Wysłano zasady Centrum Pomocy na {docelowy.mention}.", ephemeral=True)


# ========================
#   ANKIETY
# ========================

def forma_glosow(ilosc: int) -> str:
    if ilosc == 1:
        return "głos"
    if 2 <= ilosc % 10 <= 4 and not (12 <= ilosc % 100 <= 14):
        return "głosy"
    return "głosów"


def build_ankieta_embed(ankieta_id: str) -> discord.Embed:
    wpis = CONFIG["ankiety_dane"][ankieta_id]
    glosy = wpis.get("glosy", {})
    licznik = [0] * len(wpis["opcje"])
    for indeks in glosy.values():
        licznik[indeks] += 1
    razem = sum(licznik) or 1

    linie = []
    for i, opcja in enumerate(wpis["opcje"]):
        procent = round(licznik[i] / razem * 100)
        pasek = "█" * (procent // 10) + "░" * (10 - procent // 10)
        linie.append(f"**{opcja}**\n`{pasek}` {procent}% ({licznik[i]} {forma_glosow(licznik[i])})")
    opis = "\n\n".join(linie)

    if wpis.get("zakonczona"):
        stopka = f"#{ankieta_id} • Ankieta zakończona • {sum(licznik)} {forma_glosow(sum(licznik))} łącznie"
    elif wpis.get("koniec"):
        stopka = f"#{ankieta_id} • Głosuj klikając przycisk! Koniec wkrótce"
    else:
        stopka = f"#{ankieta_id} • Głosuj klikając przycisk niżej!"

    return karta(f"📊 {wpis['pytanie']}", opis, CONFIG["kolory"]["ankiety"], stopka=stopka)


class AnkietaGlosujButton(discord.ui.Button):
    def __init__(self, ankieta_id: str, indeks: int, etykieta: str, disabled: bool = False):
        super().__init__(label=etykieta[:80], style=discord.ButtonStyle.secondary,
                          custom_id=f"igrzyskamc:ankieta:{ankieta_id}:{indeks}", disabled=disabled)
        self.ankieta_id = ankieta_id
        self.indeks = indeks

    async def callback(self, interaction: discord.Interaction):
        wpis = CONFIG["ankiety_dane"].get(self.ankieta_id)
        if not wpis or wpis.get("zakonczona"):
            await interaction.response.send_message("⚠️ Ta ankieta już się zakończyła.", ephemeral=True)
            return
        glosy = wpis.setdefault("glosy", {})
        glosy[str(interaction.user.id)] = self.indeks
        save_config()
        await interaction.response.send_message(f"✅ Twój głos: **{wpis['opcje'][self.indeks]}**", ephemeral=True)
        try:
            kanal = interaction.guild.get_channel(wpis["kanal_id"])
            wiadomosc = await kanal.fetch_message(wpis["message_id"])
            await wiadomosc.edit(embed=build_ankieta_embed(self.ankieta_id), view=build_ankieta_view(self.ankieta_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


def build_ankieta_view(ankieta_id: str) -> discord.ui.View:
    wpis = CONFIG["ankiety_dane"][ankieta_id]
    widok = discord.ui.View(timeout=None)
    for i, opcja in enumerate(wpis["opcje"]):
        widok.add_item(AnkietaGlosujButton(ankieta_id, i, opcja, disabled=wpis.get("zakonczona", False)))
    return widok


async def zakoncz_ankiete(bot_instance: commands.Bot, ankieta_id: str):
    wpis = CONFIG["ankiety_dane"].get(ankieta_id)
    if not wpis or wpis.get("zakonczona"):
        return
    wpis["zakonczona"] = True
    save_config()
    kanal = bot_instance.get_channel(wpis["kanal_id"])
    if kanal:
        try:
            wiadomosc = await kanal.fetch_message(wpis["message_id"])
            await wiadomosc.edit(embed=build_ankieta_embed(ankieta_id), view=build_ankieta_view(ankieta_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


@tasks.loop(seconds=30)
async def sprawdzaj_ankiety():
    teraz = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for ankieta_id, wpis in list(CONFIG["ankiety_dane"].items()):
        if not wpis.get("zakonczona") and wpis.get("koniec") and wpis["koniec"] <= teraz:
            await zakoncz_ankiete(bot, ankieta_id)


ankieta_group = app_commands.Group(name="ankieta", description="System ankiet")


@ankieta_group.command(name="stworz", description="Tworzy nową ankietę (2-5 opcji)")
@app_commands.describe(pytanie="Treść pytania", opcja1="Opcja 1", opcja2="Opcja 2",
                        opcja3="Opcja 3 (opcjonalnie)", opcja4="Opcja 4 (opcjonalnie)",
                        opcja5="Opcja 5 (opcjonalnie)", czas="Czas trwania np. 1d, 12h (opcjonalnie - bez limitu jeśli puste)",
                        kanal="Kanał docelowy (opcjonalnie)")
async def ankieta_stworz(interaction: discord.Interaction, pytanie: str, opcja1: str, opcja2: str,
                          opcja3: Optional[str] = None, opcja4: Optional[str] = None,
                          opcja5: Optional[str] = None, czas: Optional[str] = None,
                          kanal: Optional[discord.TextChannel] = None):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return

    opcje = [o for o in [opcja1, opcja2, opcja3, opcja4, opcja5] if o]
    docelowy = kanal
    if docelowy is None:
        kanal_id = CONFIG["kanaly"].get("ankiety")
        docelowy = interaction.guild.get_channel(kanal_id) if kanal_id else interaction.channel

    koniec = None
    if czas:
        delta = parsuj_czas(czas)
        if not delta:
            await interaction.response.send_message("⚠️ Zły format czasu. Użyj np. `1d`, `12h`, `30m`.", ephemeral=True)
            return
        koniec = (datetime.datetime.now(datetime.timezone.utc) + delta).timestamp()

    ankieta_id = nastepne_id("ankieta")
    CONFIG["ankiety_dane"][ankieta_id] = {
        "pytanie": pytanie, "opcje": opcje, "glosy": {}, "koniec": koniec,
        "zakonczona": False, "kanal_id": docelowy.id, "message_id": 0,
    }
    save_config()

    await wyslij_tag(docelowy, "Ankiety", "tag_ankiety")
    embed = build_ankieta_embed(ankieta_id)
    widok = build_ankieta_view(ankieta_id)
    wiadomosc = await docelowy.send(embed=embed, view=widok)
    CONFIG["ankiety_dane"][ankieta_id]["message_id"] = wiadomosc.id
    save_config()
    bot.add_view(widok, message_id=wiadomosc.id)

    await interaction.response.send_message(f"✅ Utworzono ankietę **#{ankieta_id}** na {docelowy.mention}.", ephemeral=True)


@ankieta_group.command(name="zakoncz", description="Kończy ankietę przed czasem")
async def ankieta_zakoncz_cmd(interaction: discord.Interaction, id: str):
    if not is_staff(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    if id not in CONFIG["ankiety_dane"]:
        await interaction.response.send_message("⚠️ Nie znaleziono ankiety o takim ID.", ephemeral=True)
        return
    await zakoncz_ankiete(bot, id)
    await interaction.response.send_message(f"✅ Zakończono ankietę **#{id}**.", ephemeral=True)


# ========================
#   TICKETY
# ========================

TICKET_KATEGORIE = ["Pomoc techniczna", "Zgłoszenie gracza", "Współpraca / Biznes", "Inne"]


class TicketZamknijView(discord.ui.View):
    def __init__(self, numer: str):
        super().__init__(timeout=None)
        self.numer = numer
        przycisk = discord.ui.Button(label="Zamknij ticket", emoji="🔒", style=discord.ButtonStyle.danger,
                                      custom_id=f"igrzyskamc:ticket:zamknij:{numer}")
        przycisk.callback = self.zamknij
        self.add_item(przycisk)

    async def zamknij(self, interaction: discord.Interaction):
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
                await log_kanal.send(
                    embed=karta(f"🔒 Zamknięto ticket #{self.numer}",
                                 f"Kategoria: {wpis['kategoria']}\nAutor: <@{wpis['autor_id']}>\n"
                                 f"Zamknął: {interaction.user.mention}", CONFIG["kolory"]["tickety"]),
                    file=plik)

        await asyncio.sleep(5)
        try:
            await interaction.channel.delete()
        except (discord.NotFound, discord.Forbidden):
            pass


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
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
            gildia.me: discord.PermissionOverwrite(view_channel=True, send_messages=True),
        }
        staff_id = CONFIG["role"].get("staff")
        if staff_id:
            staff_rola = gildia.get_role(staff_id)
            if staff_rola:
                przeciazenia[staff_rola] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)

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

        embed = karta(f"🎫 Ticket #{numer} — {kategoria}",
                       f"Witaj {interaction.user.mention}! Opisz swój problem, a nasz zespół odezwie się najszybciej jak to możliwe.\n\n"
                       f"» Zanim napiszesz, sprawdź może odpowiedź jest już w Centrum Pomocy!",
                       CONFIG["kolory"]["tickety"])
        await kanal.send(content=interaction.user.mention, embed=embed, view=TicketZamknijView(numer))
        bot.add_view(TicketZamknijView(numer))
        await interaction.response.send_message(f"✅ Utworzono ticket: {kanal.mention}", ephemeral=True)


class TicketyPanel(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketySelect())


tickety_group = app_commands.Group(name="tickety", description="System ticketów")


@tickety_group.command(name="panel", description="Wysyła panel ticketów na wskazany kanał")
async def tickety_panel_cmd(interaction: discord.Interaction, kanal: discord.TextChannel):
    if not is_admin(interaction):
        await interaction.response.send_message("⚠️ Brak uprawnień.", ephemeral=True)
        return
    embed = karta("🎫 Centrum Ticketów",
                   "Potrzebujesz pomocy? Wybierz kategorię z listy niżej, a utworzymy dla Ciebie prywatny kanał "
                   "widoczny tylko dla Ciebie i naszego zespołu.",
                   CONFIG["kolory"]["tickety"])
    await kanal.send(embed=embed, view=TicketyPanel())
    await interaction.response.send_message(f"✅ Panel ticketów wysłany na {kanal.mention}.", ephemeral=True)


# ========================
#   KONFIGURACJA
# ========================

konfiguracja_group = app_commands.Group(name="konfiguracja", description="Ustawienia bota")


@konfiguracja_group.command(name="nazwa", description="Ustawia nazwę wyświetlaną w stopkach kart")
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
    app_commands.Choice(name="Propozycje", value="propozycje"),
    app_commands.Choice(name="Ankiety", value="ankiety"),
    app_commands.Choice(name="Błędy", value="bledy"),
    app_commands.Choice(name="Ogłoszenia", value="ogloszenia"),
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
    app_commands.Choice(name="Tag - Propozycje", value="tag_propozycje"),
    app_commands.Choice(name="Tag - Błędy", value="tag_bledy"),
    app_commands.Choice(name="Tag - Centrum Pomocy", value="tag_centrum_pomocy"),
    app_commands.Choice(name="Tag - Ankiety", value="tag_ankiety"),
    app_commands.Choice(name="Tag - Ogłoszenia", value="tag_ogloszenia"),
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
    app_commands.Choice(name="Pomoc", value="pomoc"),
    app_commands.Choice(name="Tickety", value="tickety"),
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


# ========================
#   OGŁOSZENIA (bonus - styl changelogu jak na screenie)
# ========================

ogloszenie_group = app_commands.Group(name="ogloszenie", description="Wysyła ogłoszenie / changelog")


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

    punkty = "\n".join(f"• {linia.strip()}" for linia in tresc.split("\\n") if linia.strip())
    embed = karta(tytul, punkty, CONFIG["kolory"]["info"])
    await wyslij_tag(docelowy, "Ogłoszenia", "tag_ogloszenia")
    await docelowy.send(embed=embed)
    await interaction.response.send_message(f"✅ Ogłoszenie wysłane na {docelowy.mention}.", ephemeral=True)


# ========================
#   START BOTA
# ========================

# ========================
#   /pomoc  — panel ze wszystkimi komendami bota
# ========================

POMOC_KATEGORIE = {
    "ogolne": {
        "etykieta": "🧭 Ogólne",
        "tresc": (
            "> Witaj w panelu pomocy bota **IgrzyskaMC.PL**! Wybierz kategorię z listy niżej, "
            "żeby zobaczyć dostępne komendy.\n\n"
            "> `/pomoc` — Pokazuje ten panel.\n\n"
            "> Zacznij od zakładki **⚙️ Konfiguracja**, jeśli dopiero ustawiasz bota od zera."
        ),
    },
    "tickety": {
        "etykieta": "🎫 Tickety",
        "tresc": (
            "> `/tickety panel <kanal>` — Wysyła panel z wyborem kategorii ticketu. *(Admin)*\n\n"
            "> Ticket tworzy się automatycznie po wybraniu kategorii przez gracza — prywatny kanał "
            "widoczny tylko dla autora i roli Staff.\n\n"
            "> Przycisk **🔒 Zamknij ticket** w kanale zapisuje transkrypt (jeśli ustawiono kanał logów) "
            "i usuwa kanał po 5 sekundach."
        ),
    },
    "centrum_pomocy": {
        "etykieta": "❓ Centrum Pomocy",
        "tresc": (
            "> `/centrumpomocy dodaj <pytanie> <odpowiedz>` — Dodaje wpis FAQ. *(Admin)*\n"
            "> `/centrumpomocy edytuj <id> <pytanie> <odpowiedz>` — Edytuje wpis. *(Admin)*\n"
            "> `/centrumpomocy usun <id>` — Usuwa wpis. *(Admin)*\n"
            "> `/centrumpomocy lista` — Pokazuje wszystkie wpisy z ID.\n"
            "> `/centrumpomocy panel <kanal>` — Wysyła panel z listą wyboru tematu. *(Admin)*\n"
            "> `/centrumpomocy zasady` — Wysyła informacje/regulamin Centrum Pomocy (godziny, zasady, dozwolone programy). *(Admin)*"
        ),
    },
    "propozycje": {
        "etykieta": "💡 Propozycje",
        "tresc": (
            "> `/propozycje panel <kanal>` — Wysyła panel z przyciskiem 'Napisz swoją propozycję'. *(Admin)*\n"
            "> `/propozycje status <id> <status>` — Zmienia status propozycji. *(Staff)*\n"
            "> `/propozycje usun <id>` — Usuwa propozycję. *(Staff)*\n\n"
            "> Gracze głosują reakcjami 👍/👎 pod każdą propozycją."
        ),
    },
    "bledy": {
        "etykieta": "🐞 Błędy",
        "tresc": (
            "> `/bledy panel <kanal>` — Wysyła panel z przyciskiem 'Zgłoś błąd'. *(Admin)*\n"
            "> `/bledy status <id> <status>` — Zmienia status zgłoszenia. *(Staff)*\n"
            "> `/bledy usun <id>` — Usuwa zgłoszenie. *(Staff)*"
        ),
    },
    "ankiety": {
        "etykieta": "📊 Ankiety",
        "tresc": (
            "> `/ankieta stworz <pytanie> <opcja1> <opcja2> [...] [czas] [kanal]` — Tworzy ankietę (2-5 opcji). *(Staff)*\n"
            "> `/ankieta zakoncz <id>` — Kończy ankietę przed czasem. *(Staff)*\n\n"
            "> Wyniki (paski % i liczba głosów) aktualizują się na żywo po każdym głosie."
        ),
    },
    "ogloszenia": {
        "etykieta": "📢 Ogłoszenia",
        "tresc": (
            "> `/ogloszenie wyslij <tytul> <tresc> [kanal]` — Wysyła ogłoszenie w stylu changelogu.\n"
            "> W treści użyj `\\n`, żeby rozbić tekst na osobne punkty (każda linijka = jeden punkt). *(Staff)*"
        ),
    },
    "konfiguracja": {
        "etykieta": "⚙️ Konfiguracja",
        "tresc": (
            "> `/konfiguracja nazwa <nazwa>` — Nazwa wyświetlana w stopkach kart. *(Admin)*\n"
            "> `/konfiguracja kanal <typ> <kanal>` — Ustawia kanał modułu (tickety, propozycje, błędy, ankiety, centrum pomocy, log ticketów, ogłoszenia). *(Admin)*\n"
            "> `/konfiguracja kategoria-ticketow <kategoria>` — Kategoria, w której tworzą się kanały ticketów. *(Admin)*\n"
            "> `/konfiguracja rola <typ> <rola>` — Rola Staff / powiadomień / tagów sekcji. *(Admin)*\n"
            "> `/konfiguracja kolor <sekcja> <hex>` — Kolor karty danej sekcji, np. `#5865F2`. *(Admin)*"
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
        await interaction.response.edit_message(embed=build_pomoc_embed(self.values[0]),
                                                  view=PomocPanel(self.values[0]))


def build_pomoc_embed(kategoria: str) -> discord.Embed:
    dane = POMOC_KATEGORIE.get(kategoria, POMOC_KATEGORIE["ogolne"])
    return karta(f"📖 Pomoc — {dane['etykieta']}", dane["tresc"], CONFIG["kolory"]["info"])


class PomocPanel(discord.ui.View):
    def __init__(self, kategoria: str = "ogolne"):
        super().__init__(timeout=300)
        self.add_item(PomocSelect(kategoria))


@bot.tree.command(name="pomoc", description="Pokazuje wszystkie dostępne komendy bota")
async def pomoc_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=build_pomoc_embed("ogolne"), view=PomocPanel(), ephemeral=True)


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


@bot.event
async def on_ready():
    bot.add_view(ZgloszeniePanel("propozycja"))
    bot.add_view(ZgloszeniePanel("blad"))
    bot.add_view(CentrumPomocyPanel())
    bot.add_view(TicketyPanel())

    for numer, wpis in list(CONFIG["tickety_dane"].items()):
        if not wpis.get("zamkniety"):
            bot.add_view(TicketZamknijView(numer))

    teraz = datetime.datetime.now(datetime.timezone.utc).timestamp()
    for ankieta_id, wpis in list(CONFIG["ankiety_dane"].items()):
        if not wpis.get("zakonczona"):
            if wpis.get("koniec") and wpis["koniec"] <= teraz:
                await zakoncz_ankiete(bot, ankieta_id)
            elif wpis.get("message_id"):
                bot.add_view(build_ankieta_view(ankieta_id), message_id=wpis["message_id"])

    if not sprawdzaj_ankiety.is_running():
        sprawdzaj_ankiety.start()

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
