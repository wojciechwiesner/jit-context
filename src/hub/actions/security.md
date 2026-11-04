# $label projektu $slug

Przeprowadź audyt bezpieczeństwa projektu w bieżącym katalogu. Nie odczytuj zawartości plików `.env` ani innych
plików z sekretami; wystarczy stwierdzić, czy istnieją i czy są śledzone przez git (`git status`, `git log`).

Sekcje raportu:

## Podsumowanie
Ogólna ocena poziomu bezpieczeństwa i trzy najpoważniejsze problemy.

## Sekrety i konfiguracja
Sekrety w kodzie lub w historii git, pliki konfiguracyjne śledzone przez git, brak `.env.example`.

## Wejście i uwierzytelnianie
Walidacja danych wejściowych, uwierzytelnianie i autoryzacja tras, CSRF, CORS, nagłówki bezpieczeństwa.

## Wstrzyknięcia i wykonanie kodu
SQL injection, command injection, path traversal, deserializacja, wywołania powłoki z danymi użytkownika.

## Zależności
Wersje bibliotek z plików manifestów; znane podatności potwierdzone źródłem (URL do CVE lub advisory).

## Znaleziska
Tabela: problem, dowód, ważność (krytyczna, wysoka, średnia, niska), sposób naprawy.

## Rekomendacje
Kroki naprawcze w kolejności ważności.
