# Журнал виконання

Що зроблено на кожному етапі, як це перевірено і що варто памʼятати далі.

## Статус

| Етап | Назва | Статус | Дата | Коміт |
|---|---|---|---|---|
| S0 | Каркас репозиторію | done | 2026-11-12 | `c7abf61` |
| S1 | PostgreSQL: схема, сід, ролі | done | 2026-11-12 | `c8e78de` |
| S2 | RabbitMQ і worker | done | 2026-11-12 | `3a68305` |
| S3 | Generator, сценарії, сторінка керування | done | 2026-11-12 | `5aecd41` |
| S4 | Авторизація і gateway | done | 2026-11-12 | `9522066` |
| S5 | Prometheus і метрики БД | done | 2026-11-12 | `61d5432` |
| S6 | Grafana і дашборди | done | 2026-11-12 | `8d25510` |
| S7 | Loki, Alloy і логи | done | 2026-11-12 | `876c663` |
| S8 | Tempo, OpenTelemetry і трейси | done | 2026-11-12 | `6efab0c` |
| S9 | Наскрізні сценарії та повний прогін | done | 2026-11-12 | `98ee132` |
| S10 | Здача: README, звіт, сценарій показу | done (очікує ручної перевірки) | 2026-11-12 | `a51e4a2` |

Статуси: `—` (не розпочато) · `in progress` · `done (очікує ручної перевірки)` · `done` · `blocked`.

## Запити на зміну плану

_Формат: що не сходиться → мінімальна зміна → які етапи й тести зачепить. Процедура — `docs/00-common.md` §9._

### Запит 1 — dev-порт PostgreSQL · 2026-11-12 · **схвалено**
- **Що не сходиться:** на робочій машині `127.0.0.1:5432` зайнятий локальним PostgreSQL, тому `make up-dev` не може опублікувати Postgres стенда на 5432 (§6.1), і S1-AC7 невиконуваний.
- **Зміна:** у dev-режимі Postgres стенда публікується на `127.0.0.1:15432`; порт усередині мережі compose лишається 5432. Змінено §6.1, вимогу 10 і S1-AC7 етапу S1.
- **Зачіпає:** `docker-compose.dev.yml` (S1), таблицю портів у README (S10). Тестів не зачіпає: вони ходять усередині мережі.
- **Рішення:** обрано варіант «dev-порт 15432».

### Запит 2 — тип блокування рахунків у worker · 2026-11-12 · **вирішено**
- **Що не сходиться:** S2-AC8 не проходив. Коли всі `MAX_ATTEMPTS` спроби переказу завершувались deadlock, окрема транзакція запису `failed` теж потрапляла у взаємне блокування: перевірка зовнішнього ключа `transfers → accounts` бере `FOR KEY SHARE`, а він конфліктує з `FOR UPDATE` інших переказів. Помилка 40P01 виходила з процесора, повідомлення йшло в `transfers.dead`, і переказ губився (11 випадків з 40 у прогоні).
- **Зміна:** рахунки блокуються `SELECT … FOR NO KEY UPDATE` — це саме той рядковий лок, який бере `UPDATE` неключових колонок. Він сумісний із `KEY SHARE`, тож запис невдачі більше не чекає на перекази, а два перекази тих самих рахунків, як і раніше, блокують один одного (сценарій `deadlocks` працює). Змінено §2 і вимогу 6 етапу S2.
- **Зачіпає:** лише `services/worker/bank_worker/processor.py`. Тести не змінюються.

### Запит 3 — домашній дашборд Grafana · 2026-11-12 · **вирішено**
- **Що не сходиться:** S6 вимагає домашній дашборд `bank-overview`. У Grafana 13 `default_home_dashboard_path` показує не наш дашборд, а окрему віртуальну копію з uid `default-home-dashboard`, і роль `Viewer` отримує на ній `403`. Provisioning налаштувань організації Grafana не має.
- **Зміна:** одноразовий сервіс `grafana-init` (образ Grafana, `curl`) після готовності Grafana виставляє `homeDashboardUID = bank-overview` через `PUT /api/org/preferences` і завершується; `gateway` залежить від нього з `service_completed_successfully`. Додано рядок у §6.1 і пояснення у вимозі 1 етапу S6.
- **Зачіпає:** `docker-compose.yml`, `tests/e2e/test_s06_grafana.py` (S6-AC5 перевіряє `homeDashboardUID` і доступ `viewer`).


## Записи

_Один запис на кожен запуск етапу, нові — в кінець._

### S0 — Каркас репозиторію · 2026-11-12
- **Результат:** done
- **AC:** S0-AC1 ✅ · S0-AC2 ✅ · S0-AC3 ✅ · S0-AC4 ✅ · S0-AC5 ✅ · S0-AC6 ✅ · S0-AC7 ✅ · S0-AC8 ✅
- **Зміни:** `.gitignore`, `.env.example`, `Makefile`, `pyproject.toml`, `docker-compose{,.dev}.yml`, `README.md`; пакет `services/common/bankmon_common` (`config`, `logging`, `metrics`); `tests/` (образ, юніт-тести, e2e-каркас); `scripts/check_images.sh`, `scripts/check_ports.sh`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Версії пакетів (PyPI, 2026-11-12): `pytest==9.2.0`, `requests==2.34.2`, `ruff==0.17.4`, `prometheus-client==0.26.0`. Ту саму версію `prometheus-client` закріплено в `services/common/pyproject.toml` — сервіси мають брати її звідти.
  - Ruff 0.17 типово форматує й Python-блоки всередині `*.md` (підтверджено `ruff config include`), тому в `pyproject.toml` перелік файлів обмежено: `include = ["*.py", "**/pyproject.toml"]`. Інакше `make lint` падає на фрагментах коду в `docs/`.
  - pytest 9.2 підміняє `sys.stdout` окремо для кожної фази тесту: потік, який обробник логів захопив під час setup фікстури, до тіла тесту вже закритий (`I/O operation on closed file`). Тому юніт-тести логування пишуть у буфер через `handler.setStream`, а запис саме в stdout перевіряє окремий тест, що викликає `setup_logging` у тілі. Те саме стосуватиметься будь-якого тесту, що налаштовує логування у фікстурі.
  - `log_event(logger, level, event, msg, /, **fields)` — перші чотири параметри лише позиційні, тож додаткове поле з назвою `level` чи `msg` не ламає виклик, а просто відкидається форматером. `exc_info=True` серед полів прикріплює виняток (`exc_type`, `exc_message`, `stack`).
  - `tests/e2e` — пакет (є `__init__.py`), `tests/` — ні. В e2e-тестах помічники імпортуються відносно: `from .helpers import wait_until`.
  - `make up` до появи першого сервісу стенда завершується `no service selected` — очікувано.
  - `scripts/check_images.sh` перевіряє не лише існування образу, а й збірку під архітектуру Docker-хоста (тут `arm64`); прогін триває близько двох хвилин.
  - `scripts/check_ports.sh` перевірено і на порушнику: контейнер-пустушка з міткою проєкту й опублікованим портом дає `PORTS FAIL`, така сама з міткою `gateway` — `PORTS OK`. У dev-режимі скрипт свідомо падає.
  - `make fmt` запускає образ `bankmon-tests` напряму з томом на запис і від імені користувача хоста.

### S1 — PostgreSQL: схема, сід, ролі · 2026-11-12
- **Результат:** done
- **AC:** S1-AC1 ✅ · S1-AC2 ✅ · S1-AC3 ✅ · S1-AC4 ✅ · S1-AC5 ✅ · S1-AC6 ✅ · S1-AC7 ✅
- **Зміни:** `db/init/01-schema.sql`, `02-seed.sql`, `03-roles.sh`; сервіс `postgres` і підключення тестів до БД у `docker-compose.yml`; dev-порт у `docker-compose.dev.yml`; `tests/e2e/helpers.py` (`db`, `check_invariants`), `conftest.py` (очікування готовності), `test_s01_db.py` (43 тести).
- **Відхилення від плану:** dev-порт PostgreSQL — `127.0.0.1:15432` за схваленим запитом 1. `check_invariants` має необовʼязковий параметр `conn`: так тест доводить, що перевірка справді ловить порушення I1, I2, I4 усередині транзакції, яку потім відкочено.
- **Нотатки:**
  - Версія пакета (PyPI, 2026-11-12): `psycopg[binary]==3.3.8`. Сервісам S2–S3 брати саме її.
  - Для колонок `GENERATED ALWAYS AS IDENTITY` ролі `bank_app` не потрібне право на послідовність — `INSERT` в `accounts` від її імені проходить (тест `test_s01_ac4_app_reads_and_writes_all_tables`).
  - У PostgreSQL 15+ у PUBLIC уже немає права `CREATE` на схему `public`, тому `CREATE TABLE` від `bank_app` забороняється без окремого `REVOKE` (`permission denied for schema public`).
  - psycopg 3 передає параметри окремо від тексту запиту, тож у `pg_stat_activity.query` видно `$1`, а не значення. Якщо тест шукає свій запит у `pg_stat_activity`, маркер треба вписувати в сам текст SQL.
  - `check_invariants()` без аргументу працює в окремому зʼєднанні з рівнем REPEATABLE READ — усі чотири перевірки бачать один знімок навіть під навантаженням.
  - Healthcheck має `start_interval: 1s`: після `make clean && make up` контейнер стає `healthy` приблизно за 2 с.
  - Префікс логу працює: рядки мають вигляд `2026-11-11 23:46:57.331 UTC [1] bank_app@bank ERROR: …` — на це спиратимуться запити Loki в S7.
  - У базовому режимі `docker compose port postgres 5432` друкує `invalid IP:0` з кодом 0 — так compose повідомляє, що порт не опубліковано. Доказ для R7 — `make check-ports` → `PORTS OK`.
  - `make check-ports` у dev-режимі свідомо падає (`postgres: 127.0.0.1:15432->5432/tcp`).
  - `make e2e` тричі поспіль: 47 passed щоразу; після `docker compose restart postgres` одразу `make e2e K=s01` → 43 passed (фікстура дочікується бази).

### S2 — RabbitMQ і worker · 2026-11-12
- **Результат:** done
- **AC:** S2-AC1 ✅ · S2-AC2 ✅ · S2-AC3 ✅ · S2-AC4 ✅ · S2-AC5 ✅ · S2-AC6 ✅ · S2-AC7 ✅ · S2-AC8 ✅ · S2-AC9 ✅ · S2-AC10 ✅ · S2-AC11 ✅ · S2-AC12 ✅ · S2-AC13 ✅ · S2-AC14 ✅
- **Зміни:** `bankmon_common.{db,amqp,messages}`; сервіс `services/worker` (`processor`, `consumer`, `settings`, `metrics`, `main`, Dockerfile); `rabbitmq` і `worker` у compose; тести `tests/unit/test_{messages,lock_order}.py`, `tests/e2e/test_s02_worker.py`, `tests/outage/`; `scripts/check_json_logs.sh`.
- **Відхилення від плану:** блокування `FOR NO KEY UPDATE` замість `FOR UPDATE` (запит 2). Інше — у нотатках.
- **Нотатки:**
  - Версія пакета (PyPI, 2026-11-12): `pika==1.4.4`. `psycopg[binary]==3.3.8` і `prometheus-client==0.26.0` — як раніше. Генератору (S3) брати ті самі.
  - `processed_at` worker записує як `clock_timestamp()`, а не типовим `now()`: `now()` — це початок транзакції, і паузи сценаріїв (`pg_sleep`) не потрапили б у різницю `processed_at - requested_at`. На цьому тримається S2-AC7.
  - Дублікати захищені двічі: перевірка `SELECT 1 FROM transfers` на початку і перехоплення `UniqueViolation` на `transfers_pkey` (два однакові повідомлення часто обробляються двома потоками одночасно). Запис `failed` використовує `ON CONFLICT DO NOTHING RETURNING id`.
  - Втрата з'єднання з БД посеред повідомлення: без `ack`, обидва з'єднання закриваються, повідомлення повертається в чергу, потік перепідключається. Відрізняється від помилки SQL перевіркою `conn.closed or conn.broken`.
  - `bank_worker_db_errors_total` рахує й очікувані помилки (40P01, 23514) — для панелі «Помилки БД за кодом SQLSTATE». Подія логу `db_error` пишеться лише для неочікуваних.
  - Серії `bank_transfers_processed_total` для `completed/none`, `failed/insufficient_funds`, `failed/deadlock` і `bank_transfer_retries_total{reason="deadlock"}` створюються одразу з нулем — щоб алерти й панелі не мали «дірок».
  - Тести S2 написано з розрахунку на фонове навантаження з S3: перевірки через рядки своїх переказів; лічильник `failed/insufficient_funds` перевіряється як «зріс щонайменше на 1». Лічильники дублікатів і мертвих повідомлень — точно, бо генератор таких не створює.
  - Статистика API керування RabbitMQ запізнюється до 5 с. Для живих даних (готові повідомлення, кількість споживачів) є `queue_counts()` — пасивне оголошення черги через AMQP.
  - Сервіс `tests` свідомо не залежить від `worker`: інакше `docker compose run tests` запускав би зупинений worker і ламав тест збою.
  - Тест збою S2-AC11 — дві фази в `tests/outage/test_s02_redelivery.py`; спільний `transfer_id` передається змінною середовища, бо репозиторій у контейнері тільки для читання, а том `tests_state` з'явиться лише в S9:
    `id=$(uuidgen | tr A-Z a-z)`; `docker compose stop worker`; `docker compose --profile test run --rm -e S02_TRANSFER_ID=$id tests pytest tests/outage/test_s02_redelivery.py -k publish_while_down`; `docker compose start worker`; те саме з `-k processed_after_start`.
  - Заміри: S2-AC8 (40 зустрічних переказів у режимі naive) ≈ 26 с; після `restart rabbitmq` S2-AC2 зелений за 3 с, після `restart postgres` — за 2 с, `RestartCount` worker = 0; `docker compose stop worker` — 0,2 с, код 0; `scripts/check_json_logs.sh worker` → `JSON LOGS OK (worker, 200)`.

### S3 — Generator, сценарії, сторінка керування · 2026-11-12
- **Результат:** done
- **AC:** S3-AC1 ✅ · S3-AC2 ✅ · S3-AC3 ✅ · S3-AC4 ✅ · S3-AC5 ✅ · S3-AC6 ✅ · S3-AC7 ✅ · S3-AC8 ✅ · S3-AC9 ✅ · S3-AC10 ✅ · S3-AC11 ✅ · S3-AC12 ✅ · S3-AC13 ✅ · S3-AC14 ✅ · S3-AC15 ✅ · S3-AC16 ✅
- **Зміни:** `bankmon_common.http`; сервіс `services/generator` (`scenarios`, `state`, `engine`, `operations`, `probe`, `api`, `metrics`, `main`, `static/control.html`); сервіс `generator` у compose, `make scenario`, `scripts/scenario.sh`; юніт-тести сценаріїв, стану, API, темпу; `tests/e2e/test_s03_generator.py`; фікстури `scenario` і `paused_generator`.
- **Відхилення від плану:** у `Scenario` додано поле `expected_alerts` — з нього сторінка керування показує очікувані алерти (§11), тож таблиця сценаріїв лишається єдиним джерелом.
- **Нотатки:**
  - Версії (PyPI, 2026-11-12): `fastapi==0.162.5`, `uvicorn==0.54.0`, `httpx==0.28.1` (тягне `starlette` 1.10). Starlette 1.10 попереджає, що `TestClient` на `httpx` застарів і радить `httpx2` — це лише попередження в юніт-тестах, пакета поза списком не додавав.
  - `PUT /control/api/state` спершу перевіряє тіло, потім пише `scenario_state`, і лише тоді змінює стан у пам'яті: `200` означає, що worker отримає нові налаштування; база недоступна → `503`, нічого не змінено.
  - Генератор переписує рядок `scenario_state` під час кожного (пере)підключення свого циклу — після рестарту БД рядок узгоджується зі станом генератора.
  - `deposit` бере рахунок із найменшим балансом через `FOR NO KEY UPDATE SKIP LOCKED`: рахунок, заблокований переказом, пропускається, і генератор не чекає.
  - uvicorn запускається з `log_config=None`, тож і його рядки йдуть у JSON через наш обробник.
  - Сторінка керування збирається з таблиці `SCENARIOS` (заглушка `<!-- SCENARIO_BUTTONS -->` у HTML); запити — на відносний `api/state`, тож працює і напряму, і за gateway.
  - **Виправлення тесту S2-AC8.** Під фоновим навантаженням тест падав: кожен потік worker кешує `scenario_state` до 1 с і перечитує лише на наступному повідомленні, тож зайнятий потік ще секунду працює за старими налаштуваннями, а пробний «повільний» переказ міг бути повільним через звичайне очікування блокування. Тепер `worker_settings` після зміни рядка чекає `SETTINGS_CACHE_S + 0,2 с` — межа випливає з контракту (§6.6). Перевірено тричі поспіль під навантаженням.
  - Для вимірювань є помічники з фіксованим вікном (`measurement_window`, `counter_deltas`, `rate_of`, `sample_for`) — це вікно спостереження, а не очікування умови; `time.sleep` як і раніше лише в `helpers.py`.
  - Фікстура сесії скидає генератор на старті лише тоді, коли він не в типовому стані, — щоб S3-AC12 перевіряв стан, у якому генератор сам піднявся після рестарту.
  - Заміри: повний `make e2e` — 78 passed за ≈4 хв; після `restart postgres` / `restart rabbitmq` лічильник операцій зростає знову за 3–4 с, `RestartCount` = 0; після рестарту посеред `deadlocks` генератор і `scenario_state` у `normal`.
  - Ручна перевірка (браузер, dev-режим, `127.0.0.1:8002/control/`): стан оновлюється, активна картка підсвічується, відлік автоповернення йде, «Пауза»/«Продовжити» працюють, при 390 px немає горизонтальної прокрутки, помилок у консолі немає.

### S4 — Авторизація і gateway · 2026-11-12
- **Результат:** done
- **AC:** S4-AC1 ✅ · S4-AC2 ✅ · S4-AC3 ✅ · S4-AC4 ✅ · S4-AC5 ✅ · S4-AC6 ✅ · S4-AC7 ✅ · S4-AC8 ✅ · S4-AC9 ✅ · S4-AC10 ✅ · S4-AC11 ✅ · S4-AC12 ✅ · S4-AC13 ✅ · S4-AC14 ✅ · S4-AC15 ✅ · S4-AC16 ✅
- **Зміни:** сервіс `services/auth` (`security`, `users`, `api`, `metrics`, `main`, `templates/login.html`); `gateway/nginx.conf`; `auth` і `gateway` у compose (єдина секція `ports`); юніт-тести безпеки, користувачів, API; `tests/e2e/test_s04_auth.py`; помічники `gateway()`, `login()`, `token()`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Версії (PyPI, 2026-11-12): `bcrypt==5.0.0`, `PyJWT==2.15.1`, `python-multipart==0.0.33`. bcrypt 5 сам відмовляє паролям понад 72 байти — API відповідає на них `422` ще до хешування.
  - PyJWT перевіряє, що `iat` не в майбутньому: токен «з 2030 року» він відкидає (на цьому впав перший варіант юніт-тесту).
  - Gateway звертається до сервісів через змінні (`set $auth_upstream …`) і `resolver 127.0.0.11`: nginx стартує, навіть коли сервіс ще не піднявся, і знаходить контейнер із новою IP після перестворення (замість граблі G13). З такою формою `proxy_pass` URI передається як є, тож у підзапиті перевірки шлях `/auth/verify?require=admin` записано повністю.
  - Підзапит `auth_request` іде методом `GET` (`proxy_method GET`): інакше для `PUT /control/api/state` він теж був би `PUT`, маршрут `/auth/verify` відповів би `405`, а nginx — `500`.
  - Заголовки `X-Auth-User` і `X-Auth-Role` задано на рівні `server` змінними з відповіді `auth`; порожнє значення означає, що заголовок не передається взагалі — тому клієнтський `X-Auth-User` до сервісів не доходить (S4-AC10). Важливо для S6: локація з власними `proxy_set_header` не успадковує серверні — там їх треба повторити.
  - `absolute_redirect off` — інакше nginx писав би в `Location` повну адресу з внутрішнім іменем хоста.
  - `rd` у перенаправленні на вхід передається як є (`$request_uri`): у nginx без модулів немає URL-кодування. Для шляхів без `&` у рядку запиту цього досить.
  - `/auth/verify` на невідоме значення `require` відповідає `400`, а не пропускає: помилка в конфігурації gateway дасть `500`, а не відкритий доступ.
  - Журнал доступу gateway — JSON (`ts` з мілісекундами зібрано з `$time_iso8601` і `$msec`); 9 рядків банера `docker-entrypoint.sh` на старті — не JSON, це нормально.
  - Помічник `GatewaySession.get` перевизначено: `requests.Session.get` сам передає `allow_redirects=True`, і тести йшли за перенаправленнями.
  - Ручна перевірка (браузер, `localhost:8080`): без входу `/control/` → форма входу; невірний пароль → `401`, «Невірний логін або пароль», логін лишився в полі; вхід `admin` → сторінка керування (`rd` збережено й після невдалої спроби); вихід → форма; `viewer` → `/control/` `403`. Наприкінці виконано вихід.
  - Заміри: повний `make e2e` — 102 passed за ≈4 хв 13 с; `make unit` — 148 passed.

### S5 — Prometheus і метрики БД · 2026-11-12
- **Результат:** done
- **AC:** S5-AC1 ✅ · S5-AC2 ✅ · S5-AC3 ✅ · S5-AC4 ✅ · S5-AC5 ✅ · S5-AC6 ✅ · S5-AC7 ✅ · S5-AC8 ✅ · S5-AC9 ✅ · S5-AC10 ✅ · S5-AC11 ✅
- **Зміни:** `observability/prometheus/prometheus.yml`, `rules/bank.yml`; `postgres-exporter` і `prometheus` у compose (+ dev-порти 9090, 9187); маршрут `/prometheus/` у gateway; помічники `prom_*`, `alert_states`, `wait_alert`; `tests/e2e/test_s05_metrics.py`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Підтверджено `--help` зафіксованих версій: експортер — `--collector.stat_statements` (типово вимкнений), підключення через `DATA_SOURCE_NAME`; Prometheus 3.15 — `--web.external-url`, `--web.route-prefix`, `--storage.tsdb.retention.time`, `--enable-feature=exemplar-storage`. В образах експортера й Prometheus є `wget` — healthcheck через нього (G2). Плагін `rabbitmq_prometheus` уже ввімкнений в образі.
  - `scrape_timeout: 4s` задано явно: типові 10 с більші за інтервал 5 с, і Prometheus такий конфіг відкидає.
  - Усі очікувані назви чужих метрик збіглися з фактичними (`pg_stat_activity_count`, `pg_locks_count`, `pg_settings_max_connections`, `pg_stat_user_tables_n_live_tup`, `rabbitmq_queue_*{queue=…}`); `pg_stat_statements` дає `pg_stat_statements_{calls,seconds,rows,block_read_seconds,block_write_seconds}_total`.
  - Prometheus 3 сам перенаправляє `/prometheus/` → `/prometheus/query`; UI посилається на ресурси відносно (`./assets/…`), тож вони вантажаться через `/prometheus/assets/…`.
  - **Граблі:** змонтовані конфіги не перечитуються самі. Після зміни `gateway/nginx.conf` — `docker compose restart gateway`; після зміни `prometheus.yml` чи правил — `docker compose restart prometheus`. `make up` не перестворює контейнер, якщо змінився лише вміст змонтованого файлу (у цьому етапі через це `/prometheus/` спершу віддавав 404).
  - Заміри: `TransferFailureRatioHigh` і `DeadlocksDetected` переходять у `firing` і назад у `inactive` у межах 120/150 с; у звичайному режимі за 60 с жодного алерту; зразок `up{job="worker"}` до перезапуску Prometheus читається й після; повний `make e2e` — 152 passed за ≈8 хв 21 с.
  - Ручна перевірка (браузер, `admin`): `/prometheus/targets` — усі шість цілей `UP`; `/prometheus/alerts` — 7 правил `INACTIVE`; усі запити сторінок — `200`.

### S6 — Grafana і дашборди · 2026-11-12
- **Результат:** done
- **AC:** S6-AC1 ✅ · S6-AC2 ✅ · S6-AC3 ✅ · S6-AC4 ✅ · S6-AC5 ✅ · S6-AC6 ✅ · S6-AC7 ✅ · S6-AC8 ✅ · S6-AC9 ✅ · S6-AC10 ✅ · S6-AC11 ✅ · S6-AC12 ✅
- **Зміни:** `observability/grafana/provisioning/{datasources,dashboards}/*.yml`; дашборди `bank-overview`, `bank-db`, `bank-app`, `bank-queue`; сервіси `grafana` і одноразовий `grafana-init` у compose (+ dev-порт 3000); маршрути `/grafana/` і `/grafana/api/live/` (WebSocket) у gateway; ціль `grafana` у Prometheus; експортер — `--collector.stat_statements.include_query`; помічники `grafana_api`, `dashboard_files`, `panel_exprs`; `tests/e2e/test_s06_grafana.py`.
- **Відхилення від плану:** запит 3 — домашній дашборд задає одноразовий сервіс `grafana-init` замість `default_home_dashboard_path`; експортер віддає текст запиту для таблиці «Найважчі запити».
- **Нотатки:**
  - Перевірено на образі: роль із заголовка auth proxy (`headers = Role:X-WEBAUTH-ROLE`) у Grafana 13.2.6 працює і з `sync_ttl = 0` синхронізується на кожному запиті (Admin → Viewer → Admin). Документація цю можливість лише згадує в прикладі. Перша перевірка помилково показала протилежне через розбиття слів у zsh — у скриптах перевірок передавати значення явно.
  - `default_home_dashboard_path` у Grafana 13 віддає окрему віртуальну копію з uid `default-home-dashboard`, яку `Viewer` відкрити не може (`403`). Тому домашній дашборд задається налаштуванням організації (`PUT /api/org/preferences`, `homeDashboardUID`) з одноразового контейнера; `gateway` залежить від нього з `service_completed_successfully` — `up --wait` це приймає (G17 перевірено).
  - Під підшляхом Grafana віддає метрики на `/grafana/metrics` (`/metrics` перенаправляє на `root_url`) — так і налаштовано ціль Prometheus.
  - Дашборди згенеровано скриптом (тимчасовим, поза репозиторієм) і перевірено на перекриття панелей. Показники огляду — два ряди по чотири (у ряд по вісім заголовки обрізались). Таблиця «Активні алерти» без алертів показує «Активних алертів немає» замість «No data». Вирази з рідкісними метриками закінчуються `or vector(0)`, частки — `clamp_min(…, 1e-9)` у знаменнику.
  - Grafana логує у JSON (`GF_LOG_CONSOLE_FORMAT=json`) — знадобиться в S7.
  - Ручна перевірка (браузер, `viewer`, 1440 px): після входу одразу відкривається «BankMonitor — огляд»; на всіх чотирьох дашбордах немає «No data» і помилок панелей; помилок WebSocket у консолі немає; запити `/grafana/api/ds/query` — `200`. Значення на огляді: 7 з 7 сервісів, ≈47 транзакцій/с, ≈14 переказів/с, відмов 0 %, p95 ≈ 5 мс.
  - Злиття S5 у `main` не змінювало дерева відносно перевіреної гілки, тому повний прогін на `main` після нього не повторювався; його покриває прогін S6 і `make verify` (S9).
  - **Виправлення перевірки інваріантів.** Повний прогін «зависав»: запит I4 у `check_invariants()` (`LEFT JOIN … GROUP BY t.id … LIMIT 5`) планувальник виконував вкладеним циклом transfers × ledger_entries (≈10¹⁰ порівнянь) — понад 4 хв на 74 тис. переказів. Тепер проводки спершу агрегуються за `transfer_id`, а потім з'єднуються з переказами: 88 мс. Умову обгорнуто в `COALESCE(…, false)` — без цього завершений переказ без проводок давав `NULL` і зникав з результату (це одразу зловив тест `test_s01_ac3_check_invariants_detects_violations[I4]`).
  - Заміри: повний `make e2e` — 222 passed за 8 хв 31 с.

### S7 — Loki, Alloy і логи · 2026-11-12
- **Результат:** done
- **AC:** S7-AC1 ✅ · S7-AC2 ✅ · S7-AC3 ✅ · S7-AC4 ✅ · S7-AC5 ✅ · S7-AC6 ✅ · S7-AC7 ✅ · S7-AC8 ✅ · S7-AC9 ✅ · S7-AC10 ✅ · S7-AC11 ✅ · S7-AC12 ✅
- **Зміни:** `observability/loki/loki.yml`, `observability/alloy/config.alloy`, дашборд `bank-logs`; сервіси `loki` і `alloy` у compose (+ dev-порти 3100, 12345); джерело Loki в Grafana; цілі `loki` і `alloy` у Prometheus; помічники `loki_query`, `loki_labels`, `wait_logs`; `tests/e2e/test_s07_logs.py`.
- **Відхилення від плану:** S7-AC2 для `rabbitmq` і `prometheus` перевіряє рядки не за 5 хвилин, а від старту стенда: ці сервіси пишуть лог лише на подіях (з'єднання, компакція, старт) і за 5 хвилин спокою можуть мовчати. Для PostgreSQL тест сам викликає помилку SQL, щоб рядок точно був свіжим.
- **Нотатки:**
  - Перевірено образами: у Loki 3.6 немає оболонки, в Alloy немає `wget`/`curl` — healthcheck для них неможливий (G2), готовність опитують тести (`/ready`, `/-/ready`). Alloy працює від root — сокет Docker читається без змін користувача (G6). Конфіг Loki проходить `loki -verify-config`, Alloy — `alloy fmt` (формат канонічний, табуляція).
  - У Loki вимкнено автоматичну мітку `service_name` (`discover_service_name: []`): мітки рівно `service`, `container`, `level`. Мітку `level` ставить лише блок `stage.match` для `worker|generator|auth` — у Grafana свої JSON-логи з рівнем `warn`, який порушив би перелік значень §6.11.
  - `discovery.docker` типово шукає нові контейнери раз на хвилину; після перестворення контейнера логи з'являлись із затримкою, і S7-AC2 падав. Інтервал — 10 с, а фікстура сесії ще й чекає, поки в Loki з'являться свіжі рядки worker.
  - S7-AC6/AC7 шукають рядки лише після моменту перемикання сценарію — інакше тест «проходив» на рядках попереднього прогону.
  - Помилки Loki `error notifying scheduler … EOF` / `context canceled` з'являються, коли клієнт обриває запит (таймаут тесту) — не дефект.
  - Перевірка дашборда: Grafana вантажить панелі лише у видимій області, тож запити всіх шести панелей виконано через `/grafana/api/ds/query` від імені `viewer`: усі `200`, кожен повертає рядки (1473 точки обсягу, 102 помилки/попередження, 2 невдалі входи з тестів…).
  - Заміри: повний `make e2e` — 234 passed за 8 хв 24 с; `make unit` — 148 passed.

### S8 — Tempo, OpenTelemetry і трейси · 2026-11-12
- **Результат:** done
- **AC:** S8-AC1 ✅ · S8-AC2 ✅ · S8-AC3 ✅ · S8-AC4 ✅ · S8-AC5 ✅ · S8-AC6 ✅ · S8-AC7 ✅ · S8-AC8 ✅ · S8-AC9 ✅ · S8-AC10 ✅ · S8-AC11 ✅ · S8-AC12 ✅ · S8-AC13 ✅ · S8-AC14 ✅ · S8-AC15 ✅
- **Зміни:** `bankmon_common.tracing` (+ `trace_id`/`span_id` у логах, трасування FastAPI в `http.py`); спани `generator.<операція>` і `worker.process_transfer`, подія `deadlock_retry`, exemplars гістограми часу обробки; `observability/tempo/tempo.yml`, сервіс `tempo` (+ dev-порт 3200), `OTEL_EXPORTER_OTLP_ENDPOINT` для трьох сервісів; зв'язки джерел Grafana (exemplars → Tempo, Loki `trace_id` → Tempo, Tempo → Loki); дашборд `bank-traces`, exemplars на панелях часу обробки; ціль `tempo` у Prometheus; помічники `tempo_search`, `tempo_trace`, `trace_spans`, `wait_traces`; `tests/unit/test_tracing.py`, `tests/e2e/test_s08_traces.py`.
- **Відхилення від плану:** немає.
- **Нотатки:**
  - Версії (PyPI, 2026-11-12): `opentelemetry-sdk==1.45.2`, `opentelemetry-exporter-otlp-proto-grpc==1.45.2`, `opentelemetry-instrumentation-{psycopg,pika,fastapi}==0.66b2` (узгоджені між собою; `grpcio` має колесо під arm64).
  - Образ Tempo 2.10 — distroless (немає оболонки й прапорця перевірки конфігу), користувач 10001; конфіг перевірено запуском. Помилок доступу до тому не було (G4 не знадобилась). Попередження «metrics-generator is not configured» очікуване: metrics-generator план не передбачає.
  - Трейс переказу: `generator.transfer` → `publish` (producer, pika) → `receive` (consumer, pika; контекст із заголовків повідомлення) → `worker.process_transfer` → SQL-спани psycopg. Інструментацію вмикає `init_tracing` до відкриття з'єднань (G20).
  - Статус `ERROR` у `worker.process_transfer` — лише для технічних збоїв (вичерпані повтори, помилка SQL, відхилене повідомлення); відмова через брак коштів — `bank.status = "failed"` зі статусом не `error`, помилку показує SQL-спан.
  - Exemplars віддаються лише у форматі OpenMetrics: `start_http_server` worker сам погоджує формат за `Accept`, Prometheus 3 його просить — перевірено (`# {trace_id="…"}` у виводі) і через `/api/v1/query_exemplars`.
  - У provisioning Grafana власні заповнювачі (`${__value.raw}`, `${__trace.traceId}`) записано з подвоєним `$`, інакше Grafana підставляє на їх місце змінні середовища.
  - **Без Tempo** (`docker compose stop tempo`): S2-AC2 зелений, p95 обробки 8,5 мс, ≈14 переказів/с. Записи SDK про помилки експорту й «Queue full» обмежено одним на 30 с фільтром на обробнику кореневого логера: фільтр на логері бачив би лише свої записи, а SDK пише з кількох модулів (спершу так і було — 5 рядків за 75 с; після виправлення 2–3).
  - S8-AC13 чекає, доки хвилинне вікно p95 заповниться звичайним навантаженням: попередні тести вмикають повільні сценарії, і разовий замір одразу після них давав 0,18 с.
  - Тест S2-AC2 при зупиненому Tempo запускається з `--noconftest`, бо фікстура сесії чекає на готовність Tempo.
  - Перевірка зв'язків через API Grafana: derived field у Loki → `tempo`, `tracesToLogsV2` у Tempo → `loki`, `exemplarTraceIdDestinations` у Prometheus → `tempo`, перевірка стану Tempo — `OK`.
  - Заміри: повний `make e2e` — 247 passed за 10 хв 49 с; `make unit` — 153 passed; `scripts/check_json_logs.sh` для worker, generator, auth — OK, усі останні рядки worker мають `trace_id`.

### S9 — Наскрізні сценарії та повний прогін · 2026-11-12
- **Результат:** done
- **AC:** S9-AC1 ✅ · S9-AC2 ✅ · S9-AC3 ✅ · S9-AC4 ✅ · S9-AC5 ✅ · S9-AC6 ✅ · S9-AC7 ✅ · S9-AC8 ✅ · S9-AC9 ✅ · S9-AC10 ✅ · S9-AC11 ✅
- **Зміни:** `tests/e2e/test_s09_scenarios.py` (чотири сценарії + ланцюжок «метрика → лог → трейс»), `tests/outage/test_s09_worker_outage.py` (три фази), фікстура `state_file`, том `tests_state` у compose, `scripts/verify.sh`, цілі `make outage-test` і `make verify`.
- **Відхилення від плану:** немає. Підлаштовувати параметри сценаріїв і пороги алертів не знадобилось.
- **Нотатки:**
  - Кожен сценарний тест: тиша (усі алерти `inactive`, черга порожня) → сценарій → обовʼязкові алерти `firing` → метрики → рядки Loki і трейси Tempo, записані після моменту перемикання → `normal` → усі алерти `inactive` ≤ 150 с, черга < 50, інваріанти. Один тест — ≈1,5 хв.
  - Тест ланцюжка спершу брав трейс, щойно той зʼявлявся, і падав: worker відправляє спани пакетами, тож трейс уже існує, а спана `worker.process_transfer` в ньому ще немає. Тепер чекає саме на цей спан.
  - `make outage-test`: фаза 0 і 2 ставлять генератор на паузу лише для знімка і завжди знімають її у `finally`; між фазами Makefile зупиняє worker і запускає його знову через `up --wait`, навіть якщо фаза 1 упала. Різниця кількості рядків `transfers` точно дорівнює кількості надісланих генератором переказів (з підтвердженням брокера) — жоден не втрачено.
  - `make verify` нічого не знає про попередній стан: `make clean`, перевірка образів, `make up`, порти, лінтер, юніт, e2e, тест збою, JSON-логи, підсумковий стан (сценарій `normal`, генератор працює, алертів немає, `RestartCount` = 0). Найдовше — e2e (≈18 хв) і перевірка образів у Docker Hub (≈1,7 хв).
  - **Ноутбук засинає під час довгих прогонів.** Другий `make e2e` (S9-AC8) «тривав» 70 хв, хоча pytest нарахував 18: з 10:40 до 11:20 UTC жоден сервіс не записав жодного рядка, а журнал живлення macOS показує «Wake from Deep Idle … lid … Using BATT». Під час сну монотонний годинник стоїть, тож таймаути тестів не спрацювали — після пробудження тест продовжився й прогін завершився `252 passed`. Довгі прогони варто запускати з відкритою кришкою або від мережі.
  - Заміри: `make verify` №1 — `VERIFY OK` за 1315 с (e2e 252 passed за 17 хв 50 с, тест збою 94 с); `make verify` №2 — `VERIFY OK` за 1275 с (e2e 17 хв 11 с). Сценарні тести S9-AC1…AC4: зелені в окремому прогоні і в обох `make verify` — тричі поспіль. Два `make e2e` поспіль на тому самому стенді без `make clean` — 252 + 252 passed. Холодний старт `make clean && make up` з наявними образами — 30 с. Витримка 10 хв у звичайному режимі: жодного алерту за 8 хв, черга 0, `RestartCount` 12 контейнерів — 0, памʼять ≈1,6 ГіБ, інваріанти виконуються.

### S10 — Здача: README, звіт, сценарій показу · 2026-11-12
- **Результат:** done (очікує ручної перевірки)
- **AC:** S10-AC1 ✅ · S10-AC2 ✅ · S10-AC3 ✅ · S10-AC4 ✅ · S10-AC5 ✅ · S10-AC6 ✅ · S10-AC7 ✅ · S10-AC8 ✅
- **Зміни:** `README.md` (12 розділів), `docs/REPORT.md` (8 розділів, 10 підрозділів реалізації, 4 аномалії по три запити, таблиця `make verify`), `docs/DEMO.md` (15 кроків, 9 хв 30 с), `docs/HOW-TO-TEST.md` (інструкція для самостійної перевірки), `docs/screenshots/` (13 знімків і таблиця, як їх отримати), `tests/e2e/test_s10_docs.py` (23 тести: кожен запит PromQL/LogQL/TraceQL із документів виконується, шляхи існують, розділи на місці, немає заглушок).
- **Відхилення від плану:** немає.
- **Ручна перевірка:** заповнити титульний блок `docs/REPORT.md` (дисципліна, тема, група, ПІБ, викладач, рік — зараз заповнювачі в кутових дужках; тест заглушок їх свідомо не чіпає), прочитати звіт, пройти `docs/DEMO.md` із секундоміром.
- **Нотатки:**
  - Скриншоти знято у вікні 1440×900 у світлій темі (Grafana — `?kiosk&theme=light`), збережено з шириною 800 пікселів. Повільний трейс узято з перших секунд `slow_queries` на порожній черзі: інакше трейс тягнеться хвилинами через чергу, і SQL-спан `pg_sleep` на ньому не видно.
  - S10-AC3 на живому стенді: без входу `/grafana/` → `302` на вхід; неправильний пароль → `401`, «Невірний логін або пароль», логін лишився в полі; `viewer` на `/control/` → `403`; дашборди й Prometheus — як на скриншотах; `docker compose stop worker` → за 60 с у черзі 847 повідомлень і алерти `QueueBacklog`, `ServiceDown`; `start` → черга порожня за 10 с; `deadlocks` → `DeadlocksDetected` за 10 с, у трейсі спан `worker.process_transfer` з подією `deadlock_retry`; `slow_queries` → exemplar на «Час обробки» → «Query with Tempo» → трейс → «Logs for this trace» → рядок worker `transfer_completed`.
  - Звірка з живим стендом виправила в документах: огляд показує «10 з 10» сервісів (рахує всі цілі Prometheus); `grafana-init` видно лише в `docker compose ps -a`; кнопка в трейсі Grafana 13 при `filterBySpanID: false` — «Logs for this trace»; рядок із `trace_id` пише лише worker (generator кожен переказ не логує).
  - Один раз «Logs for this trace» спершу не показав рядка worker: він зʼявився в Loki приблизно через хвилину. У чотирьох повторах (перезапуск worker на 15 і 65 с, `deadlocks`, повна послідовність кроків 7–12 сценарію показу) затримка доставки логів не перевищила ≈15 с після старту контейнера і ≈1,5 с у роботі, тож конфіг не змінено; у `DEMO.md` і `HOW-TO-TEST.md` додано пораду оновити запит через 10–20 с.
  - Перевірка гігієни (S10-AC7) знаходила слово-заглушку в самому тесті S10, що шукає заглушки в документах; у регулярному виразі воно тепер записане як `T[O]DO`.
  - S10-AC6: `make down`, `git clone` у тимчасову теку, там `make verify` → `VERIFY OK` за 1309 с (e2e 275 passed, юніт 153 passed, тест збою — три фази); `make clean` у клоні, клон видалено, у робочій теці `make up`. Після прогону змінено лише текст `DEMO.md` і `HOW-TO-TEST.md` — `make lint` і `make e2e K=s10` після цього знову зелені.
