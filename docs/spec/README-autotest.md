# ZAI 26Z – kontrakt API i testy automatyczne

| Plik | Opis |
| --- | --- |
| `zai-api-26z.yaml` | Kontrakt REST API (OpenAPI 3.1), który implementuje każda aplikacja. Można go otworzyć w [Swagger Editor](https://editor.swagger.io/). |
| `zai-tests.mjs` | Testy automatyczne (Node.js 20+, bez dodatkowych pakietów). |
| `zgloszenia-przyklad.csv` | Wzór pliku zgłoszeń dla trybu wsadowego. |

## Instrukcja

Uruchom testy dla swojej wdrożonej aplikacji:

```bash
node zai-tests.mjs --app https://moja-app.example.com --user admin --pass 'haslo' --stage E1
node zai-tests.mjs --app https://moja-app.example.com --user admin --pass 'haslo' --stage E2 --lighthouse
```

Jeśli API działa pod innym adresem niż interfejs, dodaj `--api https://api.moja-app.example.com`.

Testy tworzą własne serie o nazwach zaczynających się od `ZAI-TEST-`, rejestrują dla nich czujniki i przesyłają wyniki ich kluczami API, a na końcu usuwają utworzone serie. Twoje dane przykładowe pozostają nietknięte. Test danych przykładowych (F11) pomija serie z prefiksem `ZAI-TEST-` i sprawdza, czy co najmniej 3 Twoje serie mają po co najmniej 15 wyników; przed etapem E1 wprowadź je swoim generatorem.

Testy sprawdzają także, że wyników nie da się zapisać bez klucza czujnika (ani samym tokenem administratora) i że nie można ich modyfikować ani usuwać. Opcja `--lighthouse` wymaga zainstalowanej przeglądarki Chrome lub Chromium.

Proszę o dopilnowanie danych logowania w formularzu zgłoszenia: bez działającego logowania większość testów się nie wykona. Proszę je zweryfikować uruchamiając testy dokładnie z tymi danymi, które zostaną wpisane do formularza.

