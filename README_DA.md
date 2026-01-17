# 🎓 Canvas Downloader

Et simpelt værktøj til studerende, der lader dig downloade alle filer og moduler fra dine Canvas-kurser på én gang.

---

## ✨ Features
*   **Spar Timevis af Klik**: Download *alle* filer fra et kursus på med få klik. Slut med at klikke "download" på hver eneste fil i canvas.
*   **Forbliv Organiseret**: Opretter automatisk mapper, der matcher dine Canvas Moduler. Perfekt til eksamenslæsning!
*   **Offline Adgang**: Få alle dine materialer ned på harddisken, så du kan læse uden internet.
*   **Downloader Alt**: Understøtter Filer, Moduler, Panopto Videoer, Sider og Eksterne Links.
*   **Altid Opdateret**: Nye kurser tilføjet til din Canvas-konto vises automatisk i appen.
*   **Studie Mode**: Brug "Kun Pdf & Powerpoint" filteret til kun at hente det vigtigste studiemateriale (springer alt andet over).
*   **Smart & Robust**: Springer filer over du ikke har adgang til, og prøver automatisk igen ved fejl.
*   **Sikker**: Kører lokalt på din maskine. Din token gemmes sikkert på din egen computer.

---

## 💻 For Windows-brugere (Sådan kører du appen)

1.  **Download**: Hent filen `Canvas_Downloader.exe`.
2.  **Kør**: Dobbeltklik på filen for at starte.
3.  **Sikkerhedsadvarsler (Vigtigt!)**:
    *   **"Windows beskyttede din PC" (SmartScreen)**:
        *   Fordi denne app er lavet af en studerende og ikke en stor virksomhed (som Microsoft), vil Windows måske forsøge at blokere den.
        *   **Løsning**: Klik på **"Yderligere oplysninger"** (under teksten) og klik derefter på knappen **"Kør alligevel"**.
    *   **Firewall Popup**:
        *   Når appen starter, kan Windows Firewall bede om tilladelse.
        *   **Hvorfor?**: Appen kører en lille lokal "webserver" på din computer for at vise brugergrænsefladen i din browser. Den har brug for tilladelse til at "tale" med sig selv.
        *   **Løsning**: Sæt flueben i boksene og klik **"Tillad adgang"**. Det er helt sikkert.

---

## 🍎 For Mac-brugere (Sådan kører du appen)

Da `.exe`-filen kun virker på Windows, skal Mac-brugere køre applikationen via Python (bare rolig, det er ret nemt).

### Forudsætninger
1.  **Installer Python**: Download og installer den nyeste Python 3 fra [python.org](https://www.python.org/downloads/).
    *   *Bemærk: Sørg for at krydse "Add Python to PATH" af under installationen, hvis du bliver spurgt.*

### Installation & Kørsel
1.  **Download Kildekode**: Download mappen med disse filer (dette har du gjort hvis du ser denne tekst).
2.  **Åbn Terminal**: Tryk `Cmd + Mellemrum`, skriv "Terminal", og tryk Enter.
3.  **Gå til Mappen**:
    *   Skriv `cd ` (skriv cd efterfulgt af et mellemrum).
    *   Træk den downloadede mappe fra Finder ind i Terminal-vinduet (dette skriver automatisk stien).
    *   Tryk **Enter**.
4.  **Installer Afhængigheder** (Kun nødvendigt første gang):
    *   Kopier og indsæt denne kommando: `pip3 install -r requirements.txt`
    *   Tryk **Enter**.
5.  **Kør Appen**:
    *   Skriv: `python3 start.py`
    *   Tryk **Enter**.

Applikationen burde nu åbne i din browser!

### 🆘 Hjælp! Det virker ikke? (Den "Magiske" Løsning)

Hvis trinene ovenfor virker for uoverskuelige eller ikke virkede, så fortvivl ikke! Du kan få en AI til at gøre det for dig.

1.  **Download & Installer AntiGravity**: Antigravity er en AI IDE lavet af Google, som gør alt med kode super nemt. Fortæl den hvad du vil, og den gør det. Denne bruger vi til at installere og køre Canvas Downloader. Download AntiGravity her: https://antigravity.google/download.
2.  **Åbn Projektet**: Åbn Antigravity og træk denne projektmappe ind i programmet.
3.  **Spørg AI'en**: Find chat-boksen, (typisk i højre side eller bunden), vælg "Gemini 3 Pro (High)" ai-modellen og indsæt præcis denne tekst:

> "Jeg er Mac-bruger og vil gerne køre denne Canvas Downloader applikation. Jeg er ikke så teknisk. Vil du tjekke om jeg har Python installeret, hjælpe mig med at installere det nødvendige, og derefter starte programmet for mig?"

AI'en vil nu agere din personlige IT-supporter og sætte det hele op for dig!

---

### 🍏 Bonus: Lav det til en rigtig App (Mac)
Gider du ikke åbne terminalen hver gang? Du kan lave et rigtigt app-ikon på 2 minutter:

1.  Åbn appen **Automator** på din Mac (Tryk Cmd+Mellemrum og skriv "Automator").
2.  Vælg **"Applikation"** når den spørger hvad du vil oprette.
3.  I søgefeltet, skriv **"Kør Shell-script"** (eller "Run Shell Script") og træk det ind i hovedvinduet.
4.  Slet teksten indeni og indsæt det nedenstående (vigtigt: erstat "/Users/DIT_BRUGERNAVN/Downloads/canvas_downloader" med den rigtige sti til din mappe):

    ```bash
    cd /Users/DIT_BRUGERNAVN/Downloads/canvas_downloader
    /usr/local/bin/python3 start.py
    ```
(**Tip**: For at få stien, kan du bare trække mappen ind i tekstboksen)*

5.  Tryk **Cmd + S** for at gemme. Kald den "Canvas Downloader" og gem den i din **Applikationer** (Applications) mappe.
6.  **Færdig!** Nu dobbeltklikker du bare på ikonet for at starte appen.

---

## 🚀 Sådan bruger du Canvas Downloader

### Trin 1: Godkendelse (Authentication)
1.  Åbn appen.
2.  **Indtast din Canvas URL**:
    *   **Vigtigt**: Du skal bruge den *faktiske* Canvas URL, ikke din skoles login-portal.
    *   **Sådan finder du den**: Log ind på Canvas i din browser. Kig på adresselinjen **efter** du er logget ind.
    *   Den ser ofte sådan ud: `https://skolenavn.instructure.com` (selvom du gik til `canvas.skole.dk` for at komme dertil).
    *   Kopiér den URL og indsæt den i appen.
3.  **Få en API Token**:
    *   Gå til **Konto** -> **Indstillinger** på Canvas.
    *   Rul ned til **Godkendte Integrationer**.
    *   Klik **+ Ny Adgangstoken**.
    *   Kopiér den lange streng og indsæt den i appen.
4.  Klik **"Validér & Gem Token"**.

### Trin 2: Vælg Kurser
1.  Du vil se en liste over dine kurser.
2.  Vælg dem, du vil downloade (eller klik "Vælg Alle").
3.  Klik **"Fortsæt"**.

### Trin 3: Download
1.  Vælg din **Download Struktur**:
    *   **Med undermapper**: Holder filer organiseret præcis som i Canvas Moduler (Anbefales).
    *   **Flad**: Lægger alle filer for et kursus i én stor mappe.
2.  Vælg en **Destinationsmappe** på din computer.
3.  Klik **"Bekræft og Download"**.
4.  Vent på at magien sker! 🪄

---

## 📂 Hvad gør filerne i projektmappen?

*   `Canvas_Downloader.exe`: Selve programmet (Kun til Windows).
*   `start.py`: "Launcher"-scriptet der starter systemet.
*   `app.py`: Den visuelle grænseflade du ser i browseren.
*   `canvas_logic.py`: "Hjernen" der taler med Canvas og håndterer downloads.
*   `translations.py`: Indeholder al tekst på engelsk og dansk.
*   `requirements.txt`: Liste over værktøjer appen skal bruge (til Mac-brugere).

---

## ⚠️ Almindelige Problemer & Fejlfinding

*   **"Unauthorized" Fejl**:
    *   Hvis du ser en fejl der siger "unauthorized", kan din token være udløbet, eller du downloader måske for hurtigt. Appen har nu "smart retries" til at håndtere dette, så prøv bare igen.
*   **Hvid Skærm**:
    *   Hvis browservinduet bliver hvidt og ikke indlæser, skal du blot **opdatere siden** (F5 eller Cmd+R) eller lukke fanen og åbne linket igen, som vises i det sorte "Mother"-vindue.
*   **Download Hastighed**:
    *   For at være sikker og undgå at blive blokeret af Canvas, downloader appen 2 filer ad gangen. Store kurser kan tage et minut eller to. Snup en kop kaffe! ☕

---

*Lavet med ❤️ til alle studerende*
