# $label projektu $slug

Przeprowadź pełny audyt projektu w bieżącym katalogu: kod, architektura, testy, dokumentacja, stan prac
(`.planning/STATE.md`, `ROADMAP.md`, `CHANGELOG.md`, `README.md`) i historia zmian (`git log`).

Sekcje raportu:

## Podsumowanie
Trzy do pięciu zdań: czym jest projekt, w jakim jest stanie, największe ryzyko i największa szansa.

## Architektura
Główne moduły, przepływ danych, punkty wejścia, zależności zewnętrzne. Zgodność z deklarowaną architekturą.

## Jakość kodu i testy
Pliki ponad 300 linii, funkcje ponad 50 linii, martwy kod, brak testów dla kluczowych ścieżek, wyniki ostatnich
uruchomień testów, jeśli są zapisane w repozytorium.

## Dokumentacja i stan prac
Czy README, CHANGELOG i STATE.md są aktualne względem kodu i historii git. Zadania otwarte i blokery.

## Ryzyka
Tabela: ryzyko, dowód, wpływ (wysoki, średni, niski), proponowane działanie.

## Rekomendacje
Lista najwyżej dziesięciu kroków w kolejności priorytetu, każdy z dowodem i szacowanym nakładem pracy.
