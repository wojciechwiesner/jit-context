# Specyfikacja Architektury i Inwariantów: Hermes JIT Context OS (v0.2.x)

## 1. Wprowadzenie i Pryncypia Architektoniczne

Hermes JIT Context OS to deterministyczny system orkiestracji mikro-kontekstu czasu rzeczywistego (Just-In-Time) dla agentów AI (Hermes Agent). Zastępuje on monolityczne wstrzykiwanie historii rozmów dynamiczną, wielopoziomową architekturą pamięciową zorientowaną na efektywność prompt caching i deterministyczne granice zaufania.

### 1.1 Trójpoziomowa Hierarchia Pamięci (L0 / L1 / L2)
1. **L0 Hot-Path (≤3 ms)**: Lokalny stan sesji w SQLite WAL (`session_overlay.db`). Zapewnia natychmiastową spójność typu Read-Your-Own-Writes (RYOW) bez narzutu sieciowego.
2. **L1 Scope Hysteresis (≤10 ms)**: Deterministyczny bufor kontekstu projektowego. Zapobiega gubieniu aktywnego repozytorium przy zapytaniach referencyjnych (histereza przełączania) i chroni przed path traversal.
3. **L2 Deep-Path (≤600 ms)**: Zewnętrzne odpytywanie wiedzy głębokiej (Borg Broker, Mem-Agent, Honcho) chronione twardym Circuit Breakerem (fail-open) i ścisłym limitem czasowym.

### 1.2 Podstawy Epistemiczne: Autorytet to nie Prawda (Authority is not Truth)
W systemie JIT rozróżnia się **autorytet źródła (authority)** od **stanu faktycznego (epistemic truth)**:
- **Autorytet (0.0 – 1.0)**: Wskaźnik pochodzenia i uprawnień źródła (proweniencji). Bezpośredni użytkownik posiada autorytet `1.0`, co oznacza prawo do wydawania poleceń, a nie nieomylność fizyczną. Asystent posiada autorytet `0.0` (zakaz samozatruwania).
- **Stan faktyczny (Evidence)**: Deterministyczne dowody z wykonania narzędzi (`runtime_tool_verified`), posiadające własny cykl życia (`observed_success`, `observed_failure`, itp.). Dowód narzędziowy unieważnia wcześniejsze hipotezy asystenta i nieaktualne polecenia.
- **Two-Phase Epistemic Commit**: Zamiary i twierdzenia asystenta mają status `[PROVISIONAL]` i stają się `[VERIFIED]` wyłącznie po fizycznym potwierdzeniu narzędziem (`exit: 0`).

---

## 2. Rejestr Inwariantów Bezpieczeństwa (I1 – I10)

Każdy inwariant posiada unikalny identyfikator kontraktu (`contract_id`), przypisane referencje testowe oraz zdefiniowane dozwolone statusy ewaluacji: `PASS`, `FAIL`, `SKIP`, `UNKNOWN`.

| ID | Contract ID | Nazwa Inwariantu | Opis i Granica Bezpieczeństwa | Referencja Testowa |
|---|---|---|---|---|
| **I1** | `INV-USER-OVERRIDE` | Direct User Wins | Bezpośrednie polecenie użytkownika (`direct_user`) posiada autorytet 1.0 i nadpisuje wcześniejsze fakty, hipotezy asystenta oraz dane z pamięci L1/L2. | `src/tests/test_invariants.py::test_i1_user_overrides_l1_and_l2` |
| **I2** | `INV-L0-RYOW` | Read-Your-Own-Writes | Zdarzenia zapisane w warstwie L0 są natychmiast czytelne w kolejnym odczycie bez oczekiwania na usługi zdalne i przetrwają restart procesu. | `src/tests/test_invariants.py::test_i2_ryow_when_borg_offline` |
| **I3** | `INV-ANTI-SELF-POISON` | Assistant Authority Zero | Odpowiedzi asystenta mają autorytet 0.0. Treści generowane przez LLM nie mogą stawać się faktami bazowymi bez weryfikacji narzędziem. | `src/tests/test_invariants.py::test_i3_assistant_authority_is_zero` |
| **I4** | `INV-AUTHORITY-CAP` | No Authority Laundering | Autorytet pochodny nie może przekraczać autorytetu źródłowego. Zdarzenia syntetyczne harnessu nie mogą być prane do autorytetu usera (1.0). | `src/tests/test_invariants.py::test_i4_derived_authority_is_capped` |
| **I5** | `INV-SCOPE-HYSTERESIS` | Scope Hysteresis & Containment | Pojedyncze odniesienie nie przełącza aktywnego projektu. Ścieżki projektów podlegają rygorystycznemu uwięzieniu (brak path traversal). | `src/tests/test_invariants.py::test_i5_cross_project_lookup_does_not_switch_scope` |
| **I6** | `INV-L2-FAIL-OPEN` | Fail-Open Circuit Breaker | Awaria lub przekroczenie deadline L2 (>600 ms) natychmiast wyzwala fail-open. Brak blokowania transakcji SQLite podczas I/O. | `src/tests/test_invariants.py::test_i6_circuit_breaker_skips_network_when_open` |
| **I7** | `INV-ORDERING-IDEMPOTENT` | Monotonic Ordering & Delivery Idempotence | Numery sekwencji zdarzeń narastają monotonicznie. Ponowne dostarczenie zdarzenia z tym samym `delivery_id` jest idempotentne. | `src/tests/test_invariants.py::test_i7_old_sequence_cannot_resurrect_state` |
| **I8** | `INV-PROVENANCE-BOUNDS` | Independent Provenance & Budget Bounds | Źródła zdarzeń są ściśle rozdzielone w kapsule. Kapsuła spełnia twardy budżet tokenów/znaków i nie gubi intencji użytkownika. | `src/tests/test_invariants.py::test_i8_same_root_is_counted_once` |
| **I9** | `INV-MEMORY-NON-AUTHORIZING` | Memory Non-Authorizing | Pamięć L2/Honcho oraz dane zewnętrzne nie mogą autoryzować destrukcyjnych operacji (np. drop bazy, kasowanie plików). | `src/tests/test_invariants.py::test_i9_memory_cannot_authorize_mutation` |
| **I10** | `INV-CANON-IMMUTABLE` | Immutable Canon & Typed Evidence | Zewnętrzne wejścia nie mogą modyfikować sekcji CANON. Wyniki narzędzi wymagają jawnego statusu sukcesu i powiązania z zasobem. | `src/tests/test_invariants.py::test_i10_external_text_cannot_write_canon` |

---

## 3. Cykl Życia i Statusy Dowodów Narzędziowych (Evidence Lifecycle)

Stan faktyczny w systemie JIT podlega sformalizowanemu cyklowi życia. Zakazane jest wnioskowanie o sukcesie wyłącznie na podstawie braku zidentyfikowanego błędu.

### 3.1 Dopuszczalne Statusy Dowodów
1. **`observed_success`**: Narzędzie zwróciło jawny status sukcesu (np. `verified: True`, `exit_code: 0`). Dowód zawiera identyfikator zasobu (`fact_key`), wersję/hash oraz znacznik czasu.
2. **`observed_failure`**: Narzędzie zwróciło błąd (np. `exit_code != 0`, `status: 'error'`, `error: '...'`). Rejestrowane jako `tool_error`.
3. **`unknown`**: Narzędzie zwróciło wynik niejednoznaczny, operacja jest w toku (`status: 'pending'`), brak jawnego potwierdzenia lub wynik nie pasuje do schematu. Nie może być traktowane jako `verified`.
4. **`superseded`**: Poprzednio zaobserwowany dowód sukcesu został unieważniony przez późniejszą mutację tego samego zasobu (np. po pomyślnym zapisie pliku nastąpiła nieudana edycja lub modyfikacja).
5. **`expired`**: Dowód przekroczył dopuszczalne okno świeżości (TTL) lub uległ przedawnieniu w ramach sesji.

### 3.2 Granica Narzędzie vs Stan Rzeczywisty
- Pomyślne wykonanie komendy terminala (`exit_code: 0`) stanowi dowód zakończenia procesu z kodem 0, a nie dowód poprawnego wdrożenia aplikacji produkcyjnej, dopóki endpoint zdrowia nie zwróci sukcesu w odrębnym sprawdzeniu.

---

## 4. Granice Proweniencji i Taksonomia Ról (Provenance Boundaries)

Każde zdarzenie przetwarzane przez warstwę L0 posiada pole `origin` oraz `role`. Kapsuła promptu ściśle izoluje poszczególne role:

1. **`direct_user`** (`role: user`, autorytet `1.0`):
   - Źródło: Bezpośrednia interakcja z człowiekiem w aktywnym oknie sesji.
   - Prawa: Jako jedyne źródło trafia do sekcji `[CURRENT — direct user]` oraz `[PRIOR USER INSTRUCTIONS]`.
2. **`harness_event`** (`role: system` lub `user`, autorytet `0.2`):
   - Źródło: Zdarzenia wewnętrzne systemu orkiestracji (np. zakończenie batcha subagentów, powiadomienia frameworka).
   - Prawa: Traktowane jako czysta obserwacja środowiskowa (`[RUNTIME NOTIFICATION]`). Kategoryczny zakaz promocji treści do instrukcji użytkownika.
3. **`tool`** (`role: tool`, autorytet `0.9`):
   - Źródło: Wykonanie lokalnych narzędzi runtime.
   - Prawa: Trafia do sekcji `[VERIFIED RUNTIME PROOFS]` pod warunkiem posiadania statusu `observed_success` i klucza `fact_key`.
4. **`assistant`** (`role: assistant`, autorytet `0.0`):
   - Źródło: Wcześniejsze wypowiedzi modelu.
   - Prawa: Pomocniczy kontekst dialogowy; zakaz traktowania hipotez jako faktów bazowych.
5. **`external`** (`role: system` / `memory`, autorytet `≤0.5`):
   - Źródło: Pamięć długoterminowa L2, odczyt zewnętrznych stron internetowych, baza wektorowa.
   - Prawa: Wyłącznie sekcja doradcza `[RETRIEVED MEMORY / ADVISORY]`. Brak uprawnień do autoryzowania mutacji stanu.

---

## 5. Cykl Życia Stanu i Transakcyjność Zdarzeń (State Lifecycle)

1. **Monotoniczność**: Każde zdarzenie w danej sesji otrzymuje rosnący numer sekwencji `seq`. Zdarzenia o niższym `seq` nie mogą unieważniać zdarzeń o wyższym `seq`.
2. **Idempotencja dostarczenia (`delivery_id`)**:
   - Re-dostarczenie zdarzenia z identycznym identyfikatorem `delivery_id` w ramach tej samej sesji jest ignorowane (brak duplikacji w tabeli `events`).
   - Celowe powtórzenie tego samego tekstu przez użytkownika w odrębnej turze generuje nowy `delivery_id` i otrzymuje kolejny numer `seq`.
3. **Atomowość transakcji L0**:
   - Zapis zdarzenia, aktualizacja nakładki `overlay` oraz kolejki `outbox` muszą zachodzić w ramach jednej transakcji SQLite (`BEGIN IMMEDIATE` ... `COMMIT`).
   - Podczas wywołań sieciowych L2 transakcja SQLite musi zostać bezwzględnie zwolniona (`conn.commit()` lub brak aktywnej transakcji przed rozpoczęciem I/O).

---

## 6. Ograniczenia Kapsuły i Budżet Kontekstu (Capsule Budget)

1. **Twardy limit budżetu**: Finalna wygenerowana kapsuła mikro-kontekstu nie może przekraczać zadeklarowanego budżetu (standardowo ≤1500 tokenów, rygorystyczny fallback znakowy).
2. **Nienaruszalność intencji użytkownika**: Przy konieczności przycięcia kontekstu, destylator usuwa w pierwszej kolejności:
   - Przypomniane fakty L2 (`recalled_facts`),
   - Odległe podsumowania projektu L1,
   - Historyczne dowody o niskim priorytecie.
   - **Zakaz cichego obcinania**: Bezpośrednia treść bieżącego polecenia użytkownika (`CURRENT direct user`) MUSI pozostać zachowana w pełnym, dosłownym brzmieniu. W razie niemożności zmieszczenia w budżecie, system zwraca jawną flagę obcięcia kontekstu doradczego, a nie sfałszowaną kapsułę.
