# Mucha Chaser

Prosty bot Discord, który co 10 minut uruchamia 30-sekundową rundę pościgu za botem **Mucha** na kanałach głosowych.

## Jak działa

- pierwsza runda zaczyna się od razu po uruchomieniu,
- przez 30 sekund Chaser śledzi Muchę po kanałach voice,
- gdy Mucha zmieni kanał, Chaser przeskakuje za nią,
- gdy Mucha wyjdzie z voice w trakcie rundy, Chaser również wychodzi i czeka,
- po 30 sekundach Chaser zawsze rozłącza się z voice,
- kolejna runda startuje dokładnie 10 minut od początku poprzedniej rundy.

Domyślnie oznacza to 30 sekund pościgu i 9 minut 30 sekund przerwy.

## Instalacja

W PowerShell:

```powershell
py -m pip install -U "discord.py[voice]>=2.7.1,<3" python-dotenv
```

Skopiuj `.env.example` jako `.env`:

```env
DISCORD_TOKEN=TOKEN_NOWEGO_BOTA
MUCHA_BOT_ID=ID_BOTA_MUCHA
CHASE_INTERVAL=600
CHASE_DURATION=30
CHASE_DELAY=0.5
```

Nie wrzucaj pliku `.env` do repozytorium.

## Uruchomienie

```powershell
py bot.py
```

## Uprawnienia Discord

Chaser potrzebuje co najmniej:

- View Channels
- Connect

FFmpeg nie jest potrzebny, ponieważ bot nie odtwarza dźwięku.
