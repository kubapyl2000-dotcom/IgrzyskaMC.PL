# IgrzyskaMC.PL — Bot Discord

## 1. Instalacja zależności

```bash
pip install -r requirements.txt
```

## 2. Zmienne środowiskowe

Ustaw je w panelu hostingu (albo w pliku `.env`, jeśli hosting to wspiera):

| Zmienna         | Wymagane | Opis                                                                 |
|-----------------|----------|-----------------------------------------------------------------------|
| `DISCORD_TOKEN` | tak      | Token bota z Discord Developer Portal → Bot → Token                  |
| `TEST_GUILD_ID` | nie      | ID Twojego serwera — jeśli ustawione, komendy syncują się natychmiast zamiast czekać do ~1h |

## 3. Discord Developer Portal — co włączyć

**Bot → Privileged Gateway Intents** — włącz:
- Server Members Intent
- Message Content Intent

**OAuth2 → URL Generator** — link zaproszenia MUSI zawierać oba scope'y:
- `bot`
- `applications.commands`

(uprawnienia: co najmniej `Manage Channels`, `Manage Roles`, `Send Messages`, `Read Message History`, `Add Reactions` — albo po prostu `Administrator` na start)

## 4. Uruchomienie

```bash
python igrzyskamc_bot.py
```

W logach powinno pojawić się: `Zalogowano jako [nazwa bota] — bot gotowy.`

## 5. Pierwsza konfiguracja na serwerze (komendy administracyjne)

```
/konfiguracja rola typ:Staff rola:@Staff
/konfiguracja kanal typ:Propozycje kanal:#propozycje
/konfiguracja kanal typ:Błędy kanal:#bledy
/konfiguracja kanal typ:Ankiety kanal:#ankiety
/konfiguracja kanal typ:"Centrum Pomocy" kanal:#centrum-pomocy
/konfiguracja kanal typ:"Log ticketów (transkrypty)" kanal:#ticket-logi
/konfiguracja kategoria-ticketow kategoria:"TICKETY"

/tickety panel kanal:#tickety
/centrumpomocy panel kanal:#centrum-pomocy
/propozycje panel kanal:#propozycje
/bledy panel kanal:#bledy
```

Dodaj kilka pytań do Centrum Pomocy, zanim wyślesz panel:
```
/centrumpomocy dodaj pytanie:"Jak dołączyć do serwera?" odpowiedz:"Wpisz w Minecrafcie adres: play.igrzyskamc.pl"
```

Reszta (`/ankieta stworz`, `/ogloszenie wyslij`, zmiana kolorów przez `/konfiguracja kolor`) — używana na bieżąco, bez dodatkowej konfiguracji.

## 6. Pliki danych

Bot zapisuje wszystkie dane (config, tickety, propozycje, błędy, ankiety, FAQ) w pliku `config.json` obok skryptu — upewnij się, że hosting nie kasuje tego pliku między restartami (potrzebny trwały dysk/wolumin).
