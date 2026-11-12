# Частина 1 — Застосунок (етапи S0–S4)

Після цих пʼяти етапів працює весь «банк»: база, черга, обробник переказів, генератор навантаження зі сценаріями, вхід за логіном і паролем. Спостережуваності ще немає — її додає частина 2 до вже готової системи.

**Спершу прочитай** `docs/00-common.md` повністю. Усі назви, порти, таблиці, метрики й формати нижче — посилання на його §6; тут вони не повторюються.

---

## Етап S0 — Каркас репозиторію

**Мета:** порожній, але робочий каркас: git, Makefile, compose з контейнером тестів, спільний Python-пакет, лінтер і перший зелений тест. Версії образів із §3 підтверджено.

**Залежить від:** нічого. Перевірка: `docker version` і `docker compose version` працюють.

**Файли:**

- створити `.gitignore`, `.env.example`, `Makefile`, `pyproject.toml`, `docker-compose.yml`, `docker-compose.dev.yml`, `README.md`;
- створити `services/common/pyproject.toml`, `services/common/bankmon_common/{__init__,config,logging,metrics}.py`;
- створити `tests/Dockerfile`, `tests/requirements.txt`, `tests/unit/test_config.py`, `tests/unit/test_logging.py`, `tests/e2e/{__init__,conftest,helpers}.py`, `tests/e2e/test_s00_env.py`;
- створити `scripts/check_images.sh`, `scripts/check_ports.sh`.

**Вимоги:**

1. **Git.** Якщо репозиторію ще немає: `git init -b main`, перший коміт `docs: project plan` з наявною текою `docs/`. Далі — гілка `stage/s0-scaffold`.
2. **`.gitignore`:** `.env`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `.DS_Store`, `.venv/`.
3. **`.env.example`** — дослівно з §6.3.
4. **`docker-compose.yml`:** `name: bankmon`; єдиний сервіс `tests` з `profiles: ["test"]`, збіркою з `tests/Dockerfile` (контекст — корінь), `env_file: .env`, томом `.:/repo:ro`, `working_dir: /repo`, змінною `PYTHONPATH=/repo/services/common:/repo/services/worker:/repo/services/generator:/repo/services/auth:/repo` та `PYTHONDONTWRITEBYTECODE=1`. Наступні етапи додають сервіси в цей самий файл.
5. **`docker-compose.dev.yml`:** порожній перелік сервісів; кожен етап додає сюди публікацію портів зі стовпця «dev» §6.1 у вигляді `127.0.0.1:<порт>:<порт>`.
6. **`tests/Dockerfile`:** база `python:3.13.18-slim`; встановлює `tests/requirements.txt`. Код не копіюється — він приходить томом. У `tests/requirements.txt` зараз: `pytest`, `requests`, `ruff`, `prometheus-client`; наступні етапи дописують свої пакети сюди ж.
7. **`pyproject.toml`:** ruff — довжина рядка 100, ціль `py313`, правила `E`, `F`, `I`, `B`, `UP`, `SIM`; pytest — маркер `slow`, параметри `-p no:cacheprovider -ra`.
8. **`Makefile`** — цілі з §6.14, які вже мають сенс: `env`, `up`, `up-dev`, `down`, `clean`, `ps`, `logs`, `lint`, `fmt`, `unit`, `e2e`, `check-ports`. Правила:
   - `env` копіює `.env.example` у `.env`, тільки якщо `.env` немає; кожна ціль, що викликає compose, залежить від `env`;
   - `up` = `env` + `docker compose up -d --build --wait`; `up-dev` додає `-f docker-compose.dev.yml`. Поки в compose немає жодного сервісу стенда (до етапу S1), `make up` запускати нічого й може завершитися повідомленням compose про відсутність сервісів — це очікувано, на S0 ця ціль не перевіряється;
   - `lint`, `unit`, `e2e` спершу тихо збирають образ `tests`, потім виконують команду через `docker compose --profile test run --rm tests …`; `lint` і `unit` запускаються з `--no-deps`, щоб не піднімати стенд;
   - `lint` = `ruff check --no-cache .` і `ruff format --check --no-cache .`; `fmt` = `ruff format` з томом на запис;
   - `e2e` = `pytest tests/e2e -q`, а якщо задано `K` — додає `-k "$(K)"`;
   - є ціль `help`, що друкує перелік цілей; вона типова.
9. **`bankmon_common.config`:** `env_str(name, default=None)`, `env_int(...)`, `env_float(...)`, `env_bool(...)`. Немає змінної й немає типового значення → `RuntimeError` з назвою змінної.
10. **`bankmon_common.logging`:**
    - `setup_logging(service: str, level: str | None = None) -> None` — один обробник stdout на кореневому логері, формат §6.11; рівень із `LOG_LEVEL`, типово `info`;
    - `log_event(logger, level, event, msg, **fields) -> None` — запис із ключем події та додатковими полями;
    - запис стороннього логера без `event` отримує `event = "log"`;
    - виняток додає поля `exc_type`, `exc_message`, `stack`;
    - додаткові поля не можуть перезаписати обовʼязкові; значення, які не серіалізуються в JSON, перетворюються через `str`.
11. **`bankmon_common.metrics`:** константи `DURATION_BUCKETS` і `E2E_BUCKETS` (§6.9); `register_build_info(service: str) -> None`; `start_metrics_server(port: int = 8000) -> None`.
12. **`tests/e2e/helpers.py`:** `wait_until(fn, timeout=30.0, interval=0.5, desc="")` — викликає `fn`, доки вона не поверне істинне значення; після таймауту — `AssertionError` з `desc` та останнім значенням чи винятком.
13. **`scripts/check_images.sh`:** для кожного з десяти образів §3 виконує `docker manifest inspect`; друкує рядок на образ і наприкінці `IMAGES OK (10)`; будь-яка помилка — ненульовий код.
14. **`scripts/check_ports.sh`:** серед запущених контейнерів проєкту `bankmon` порти на хості може мати лише `gateway`; друкує `PORTS OK` або перелік порушників і ненульовий код. Якщо контейнерів немає — `PORTS OK`.
15. **`README.md`:** заголовок, один абзац про проєкт і посилання на `docs/00-common.md`. Повний README — етап S10.

**Поза межами етапу:** будь-які сервіси стенда, Dockerfile сервісів, цілі `scenario`, `outage-test`, `verify`.

**Acceptance criteria:**

- **S0-AC1.** `docker compose config -q` і `docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q` завершуються з кодом 0.
- **S0-AC2.** `make lint` зелений.
- **S0-AC3.** `make unit` зелений. Тести `test_logging.py` доводять: рядок логу — валідний JSON з усіма обовʼязковими полями §6.11; `ts` закінчується на `Z` або `+00:00` і містить мілісекунди; додаткові поля `log_event` потрапляють у рядок; обовʼязкове поле не перезаписується; виняток дає `exc_type`, `exc_message`, `stack`; запис без `event` має `event = "log"`; рівень `debug` не друкується при `LOG_LEVEL=info`. Тести `test_config.py`: типове значення, приведення типів, `RuntimeError` для відсутньої змінної.
- **S0-AC4.** `rm -f .env && make env` створює `.env`, ідентичний `.env.example`; повторний `make env` не перезаписує змінений `.env`.
- **S0-AC5.** `scripts/check_images.sh` друкує `IMAGES OK (10)`.
- **S0-AC6.** `make e2e` зелений: тест `test_s00_ac6_env` бачить у контейнері всі змінні з `.env.example`.
- **S0-AC7.** `git check-ignore .env` повертає `.env`; у `git ls-files` немає `.env`.
- **S0-AC8.** `make` без аргументів друкує довідку з усіма цілями.

**Перевірка:**

```bash
docker compose config -q && docker compose -f docker-compose.yml -f docker-compose.dev.yml config -q
rm -f .env && make env && diff .env .env.example
scripts/check_images.sh
make lint unit e2e
scripts/check_ports.sh
git check-ignore .env
```

**Ручна перевірка:** немає.

---

## Етап S1 — PostgreSQL: схема, сід, ролі

**Мета:** контейнер PostgreSQL зі схемою, 200 рахунками, трьома ролями та налаштуваннями журналювання з §6.4.

**Залежить від:** S0. Перевірка: `make lint unit e2e` зелені.

**Файли:**

- створити `db/init/01-schema.sql`, `db/init/02-seed.sql`, `db/init/03-roles.sh`, `tests/e2e/test_s01_db.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `tests/requirements.txt`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `postgres`:** образ із §3; том `pg_data`; змінні `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `APP_DB_USER`, `APP_DB_PASSWORD`, `MONITOR_DB_USER`, `MONITOR_DB_PASSWORD` з `.env`; `db/init` змонтовано в `/docker-entrypoint-initdb.d` тільки для читання; `restart: unless-stopped`.
2. **Налаштування сервера** з §6.4 передаються прапорцями `-c` у `command`. Окремого файлу конфігурації немає.
3. **Healthcheck** через TCP: `pg_isready -h 127.0.0.1 -U <користувач> -d <база>`, інтервал 5 с. Саме TCP: під час ініціалізації тимчасовий сервер слухає лише сокет, і перевірка через сокет спрацювала б зарано.
4. **`01-schema.sql`:** розширення `pg_stat_statements` і таблиці з індексами дослівно з §6.4.
5. **`02-seed.sql`:** сід із §6.4 через `generate_series`; обидві вставки рахунків і записів `opening` — в одній транзакції.
6. **`03-roles.sh`:** створює `bank_app` і `bank_monitor` з правами з §6.4. Паролі передаються в `psql` як змінні й підставляються з екрануванням (`:'var'`), а не конкатенацією рядка. Скрипт починається з `set -euo pipefail` і запускає `psql` з `-v ON_ERROR_STOP=1`.
7. **Сервіс `tests`** отримує змінні `PG_ADMIN_DSN`, `PG_APP_DSN`, `PG_MONITOR_DSN` (зібрані в compose з `.env`) і `depends_on` на `postgres` зі `service_healthy`. У `tests/requirements.txt` додається `psycopg[binary]`.
8. **`helpers.py`:** `db(role="admin")` — контекстний менеджер, що повертає зʼєднання psycopg відповідної ролі; `check_invariants()` — перевіряє I1–I4 одним запитом на кожен інваріант і повертає перелік порушень.
9. **`conftest.py`:** фікстура рівня сесії чекає, доки `SELECT 1` від імені `bank_app` пройде (до 180 с).
10. **Dev-режим:** порт контейнера 5432 публікується як `127.0.0.1:15432` (на хості 5432 часто зайнятий локальним PostgreSQL).

**Поза межами етапу:** будь-який Python-код сервісів, RabbitMQ, експортер.

**Acceptance criteria:**

- **S1-AC1.** Після `make clean && make up` контейнер `postgres` має стан `healthy` не пізніше ніж за 60 с.
- **S1-AC2.** Схема відповідає §6.4: тест порівнює таблиці, колонки, типи, `NOT NULL` та індекси з очікуваним описом. Обмеження діють (кожна спроба — у транзакції, що відкочується): відʼємний баланс; `from_account = to_account`; `status = 'pending'`; `failed` без `fail_reason`; `completed` із `fail_reason`; другий рядок у `scenario_state`; `lock_order = 'random'` — усі дають помилку обмеження.
- **S1-AC3.** Рахунків рівно 200 з `id` 1…200 та іменами `Клієнт 001`…`Клієнт 200`; записів `opening` рівно 200, кожен із `delta = 10000.00`; рядок `scenario_state` один. `check_invariants()` повертає порожній перелік.
- **S1-AC4.** Ролі: `bank_app` виконує `SELECT`, `INSERT`, `UPDATE` на всіх чотирьох таблицях, а `DELETE`, `TRUNCATE` і `CREATE TABLE` дають `InsufficientPrivilege`. `bank_monitor` бачить у `pg_stat_activity` текст запиту чужої сесії, читає `accounts`, а `UPDATE accounts` дає `InsufficientPrivilege`.
- **S1-AC5.** `SHOW` повертає: `log_min_duration_statement` = `200ms`, `log_lock_waits` = `on`, `deadlock_timeout` = `500ms`, `track_io_timing` = `on`; `shared_preload_libraries` містить `pg_stat_statements`; `SELECT count(*) FROM pg_stat_statements` виконується від імені `bank_monitor`.
- **S1-AC6.** Дані переживають `docker compose restart postgres`: кількість рядків `ledger_entries` до й після однакова. `make clean && make up` повертає початковий сід.
- **S1-AC7.** У dev-режимі `docker compose port postgres 5432` показує `127.0.0.1:15432`; у базовому режимі порт не опубліковано.

**Перевірка:**

```bash
make clean && make up && docker compose ps
make lint unit e2e
docker compose exec postgres psql -U bank_admin -d bank -c "SELECT count(*) FROM ledger_entries"
docker compose restart postgres && make e2e K=s01
make down && make up-dev && docker compose port postgres 5432 && make down && make up
scripts/check_ports.sh
```

**Ручна перевірка:** немає.

---

## Етап S2 — RabbitMQ і worker

**Мета:** повідомлення `TransferRequested` з черги перетворюється на коректну транзакцію переказу. Worker витримує конкуренцію, взаємні блокування, дублікати, зіпсовані повідомлення й перезапуск сусідів.

**Залежить від:** S1. Перевірка: `make e2e K=s01` зелений.

**Файли:**

- створити `services/common/bankmon_common/{db,amqp,messages}.py`;
- створити `services/worker/Dockerfile`, `services/worker/requirements.txt`, `services/worker/bank_worker/{__init__,main,consumer,processor,settings,metrics}.py`;
- створити `tests/unit/test_messages.py`, `tests/unit/test_lock_order.py`, `tests/e2e/test_s02_worker.py`, `tests/outage/{__init__,conftest,test_s02_redelivery}.py`, `scripts/check_json_logs.sh`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `tests/requirements.txt`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `rabbitmq`:** образ із §3; том `rabbitmq_data`; облікові дані з `.env`; `hostname: rabbitmq` (інакше після перестворення контейнера дані тому не підхопляться); healthcheck `rabbitmq-diagnostics -q ping`; `restart: unless-stopped`.
2. **`bankmon_common.db`:** `connect(dsn, *, application_name, autocommit=False)` — повертає зʼєднання psycopg; повторює спроби з паузою, що росте від 1 до 10 с, і пише `connection_lost` з `target = "postgres"` при кожній невдачі.
3. **`bankmon_common.amqp`:** константи назв із §6.5; `connect(url)` з тими самими повторними спробами (`target = "rabbitmq"`); `declare_topology(channel)` — оголошує всі чотири обʼєкти §6.5.
4. **`bankmon_common.messages`:** незмінний датаклас `TransferRequested` з полями §6.5 (`amount` — `Decimal`, `requested_at` — `datetime` з поясом); `encode() -> bytes`; `decode(body: bytes) -> TransferRequested`, що кидає `InvalidMessage` з причиною при будь-якому порушенні правил валідності §6.5.
5. **`bank_worker.settings`:** датаклас `ScenarioSettings(scenario, lock_order, lock_gap_ms, sleep_ms)`; клас-кеш, що читає рядок `scenario_state` і перечитує його, коли з попереднього читання минуло більше 1 с. Читання виконується поза транзакцією переказу.
6. **`bank_worker.processor`:**

   ```python
   MAX_ATTEMPTS = 3

   @dataclass(frozen=True)
   class Outcome:
       status: str            # "completed" | "failed" | "duplicate"
       reason: str | None     # None | "insufficient_funds" | "deadlock"
       attempts: int

   def order_accounts(from_account: int, to_account: int, lock_order: str) -> tuple[int, int]: ...
   def process_transfer(conn, msg: TransferRequested, get_settings) -> Outcome: ...
   ```

   Алгоритм `process_transfer`:

   1. Якщо рядок `transfers` з таким `id` уже є → `Outcome("duplicate", None, 0)`.
   2. До `MAX_ATTEMPTS` спроб. На початку кожної — свіжі `ScenarioSettings`. Усередині однієї транзакції, саме в такому порядку:
      - `SELECT id FROM accounts WHERE id = %s FOR NO KEY UPDATE` для першого рахунку за `order_accounts` (не `FOR UPDATE`: той конфліктує з блокуваннями `KEY SHARE` перевірок зовнішніх ключів, і запис невдалого переказу сам потрапляв би у взаємне блокування);
      - якщо `lock_gap_ms > 0` → `SELECT pg_sleep(%s)`;
      - той самий `SELECT … FOR NO KEY UPDATE` для другого рахунку;
      - якщо будь-який із рахунків не знайдено → виняток `UnknownAccount`;
      - якщо `sleep_ms > 0` → `SELECT pg_sleep(%s)`;
      - `INSERT INTO transfers` зі статусом `completed` і номером спроби в `attempts`;
      - `UPDATE accounts SET balance = balance - %s, updated_at = now()` для відправника;
      - `UPDATE accounts SET balance = balance + %s, updated_at = now()` для отримувача;
      - два `INSERT INTO ledger_entries` (`transfer_out`, `transfer_in`).
   3. `CheckViolation` (брак коштів) → транзакція відкочується; окремою транзакцією `INSERT INTO transfers` зі статусом `failed`, причиною `insufficient_funds` і `ON CONFLICT (id) DO NOTHING`; результат `failed`.
   4. `DeadlockDetected` → відкат, лічильник повторів, подія `deadlock_retry`, пауза випадкова 50–150 мс, наступна спроба. Спроби вичерпано → запис `failed` з причиною `deadlock` так само, як у пункті 3.
   5. Баланс у Python не перевіряється: відмову дає обмеження `CHECK` у БД. Це навмисно — так помилку видно в статистиці та логах PostgreSQL.
7. **`bank_worker.consumer`:** один потік = одне зʼєднання з БД (`application_name = "bank-worker"`) + одне зʼєднання з RabbitMQ. Після підключення: `declare_topology`, `basic_qos(prefetch_count=1)`, споживання з ручним підтвердженням. Реакція на результат:
   - `completed`, `failed`, `duplicate` → `ack`;
   - `InvalidMessage`, `UnknownAccount` → `reject` без повторної постановки, подія `message_rejected`, лічильник `bank_worker_messages_dead_lettered_total`;
   - втрата зʼєднання з БД чи чергою → без `ack`; закрити обидва зʼєднання, підключитися знову (повідомлення повернеться в чергу само);
   - будь-який інший виняток → подія `db_error` або `message_rejected`, `reject` без повторної постановки. Потік не падає.
8. **`bank_worker.main`:** `setup_logging`, метрики на порту 8000, `WORKER_CONCURRENCY` потоків-споживачів. `SIGTERM` і `SIGINT` зупиняють споживання через `add_callback_threadsafe`, потоки дочікуються поточного повідомлення, процес виходить із кодом 0 не довше ніж за 10 с.
9. **`bank_worker.metrics`:** усі метрики `worker` з §6.9. `bank_transfers_processed_total` рахує тільки `completed` і `failed`; дублікати — окремим лічильником.
10. **Логи:** події `worker` з §6.11. Логер `pika` — рівень `warning`.
11. **Сервіс `worker`:** збірка з контекстом `./services` і `worker/Dockerfile`; база `python:3.13.18-slim`; процес працює не від root; `depends_on` на `postgres` і `rabbitmq` зі `service_healthy`; healthcheck — `GET http://127.0.0.1:8000/metrics` засобами Python; `stop_grace_period: 15s`; `restart: unless-stopped`.
12. **Сервіс `tests`:** змінні `AMQP_URL`, `RABBITMQ_API=http://rabbitmq:15672`, `RABBITMQ_DEFAULT_USER`, `RABBITMQ_DEFAULT_PASS`, `WORKER_URL=http://worker:8000`. У `tests/requirements.txt` додається `pika`.
13. **`helpers.py`:** `publish_transfer(from_account, to_account, amount, *, transfer_id=None, scenario="normal") -> str`; `publish_raw(body: bytes)`; `wait_transfer(transfer_id, timeout=10) -> dict`; `metric_value(url, name, labels=None) -> float`; `queue_info(name) -> dict` (через API керування RabbitMQ); `worker_settings(lock_order, lock_gap_ms, sleep_ms)` — контекстний менеджер, що змінює рядок `scenario_state` від імені адміністратора і в `finally` повертає значення `normal`.
14. **Тестові рахунки.** Наскрізні тести цього етапу використовують рахунки `id` 191…200. Твердження формулюються через записи журналу конкретного переказу та інваріанти, а не через порівняння балансу «до і після»: з етапу S3 рахунки паралельно змінює генератор.
15. **`scripts/check_json_logs.sh <сервіс>`:** бере останні 200 рядків логу сервісу й перевіряє, що кожен — JSON з усіма обовʼязковими полями §6.11; друкує `JSON LOGS OK (<сервіс>, <кількість>)`.

**Поза межами етапу:** генератор, трейсинг, HTTP-API у worker, будь-які зміни схеми БД.

**Acceptance criteria:**

- **S2-AC1.** Після `make up` `rabbitmq` і `worker` у стані `healthy`. Черга `transfers.requested` існує, durable, має аргумент `x-dead-letter-exchange = bank.dlx` і рівно `WORKER_CONCURRENCY` споживачів; черга `transfers.dead` існує.
- **S2-AC2.** Валідний переказ 200 → 199 на `25.50` за ≤ 5 с дає рядок `transfers` зі статусом `completed`, `attempts = 1`, і рівно два записи журналу: `transfer_out` з `-25.50` для 200 та `transfer_in` з `+25.50` для 199.
- **S2-AC3.** Переказ на `1000000.00` дає рядок `failed` з `fail_reason = 'insufficient_funds'`, жодного запису журналу; лічильник `bank_transfers_processed_total{status="failed",reason="insufficient_funds"}` зростає на 1.
- **S2-AC4.** Одне й те саме повідомлення, опубліковане двічі, дає один рядок `transfers` і два записи журналу; `bank_worker_duplicates_total` зростає на 1.
- **S2-AC5.** Чотири зіпсовані повідомлення — не JSON; `from_account = to_account`; `amount = "-5.00"`; неіснуючий рахунок `999999` — опиняються в `transfers.dead` (тест їх звідти вичитує); `bank_worker_messages_dead_lettered_total` зростає на 4; наступний валідний переказ обробляється.
- **S2-AC6.** 300 переказів між рахунками 196…200, опублікованих поспіль, усі мають рядок у `transfers` не пізніше ніж за 30 с; `check_invariants()` порожній.
- **S2-AC7.** З `worker_settings("sorted", 0, 300)` для опублікованого переказу різниця `processed_at - requested_at` не менша за 0,3 с. Після виходу з контексту й спорожнення черги для наступного переказу ця різниця менша за 0,2 с.
- **S2-AC8.** З `worker_settings("naive", 150, 0)` сорок переказів, що чергуються 199 → 200 і 200 → 199: `pg_stat_database.deadlocks` для бази `bank` зростає щонайменше на 1; `bank_transfer_retries_total{reason="deadlock"}` зростає; усі сорок мають рядок (`completed` або `failed` з причиною `deadlock`); серед `completed` є рядки з `attempts > 1`; `check_invariants()` порожній.
- **S2-AC9.** `GET worker:8000/metrics` містить усі метрики `worker` з §6.9 і `bank_build_info{service="worker"}`.
- **S2-AC10.** Після `docker compose restart rabbitmq` і після `docker compose restart postgres` тест `S2-AC2` знову зелений не пізніше ніж за 60 с, а `RestartCount` контейнера `worker` дорівнює 0.
- **S2-AC11.** Переказ, опублікований при зупиненому `worker`, обробляється після його запуску.
- **S2-AC12.** `docker compose stop worker` завершується швидше ніж за 12 с, код виходу контейнера 0.
- **S2-AC13.** `scripts/check_json_logs.sh worker` друкує `JSON LOGS OK`; у логах є події `worker_started` і `transfer_completed`.
- **S2-AC14.** Юніт-тести: `decode(encode(x)) == x`; кожне правило валідності §6.5 має тест на порушення; `order_accounts` для `sorted` повертає пару за зростанням незалежно від напрямку, для `naive` — `(from, to)`.

**Перевірка:**

```bash
make up && docker compose ps
make lint unit e2e
docker compose restart rabbitmq && sleep 5 && make e2e K=s02_ac2
docker compose restart postgres && sleep 5 && make e2e K=s02_ac2
docker inspect -f '{{.RestartCount}}' "$(docker compose ps -q worker)"
docker compose stop worker
docker compose --profile test run --rm tests pytest tests/outage/test_s02_redelivery.py -q -k publish_while_down
docker compose start worker
docker compose --profile test run --rm tests pytest tests/outage/test_s02_redelivery.py -q -k processed_after_start
time docker compose stop worker && docker inspect -f '{{.State.ExitCode}}' "$(docker compose ps -aq worker)" && docker compose start worker
scripts/check_json_logs.sh worker
```

`S2-AC11` перевіряють два тести у `tests/outage/test_s02_redelivery.py` (тека `tests/outage` не входить у `make e2e`): `test_publish_while_down` публікує переказ із фіксованим `transfer_id` і переконується, що рядка ще немає; `test_processed_after_start` чекає на рядок із цим `transfer_id`.

**Ручна перевірка:** немає.

---

## Етап S3 — Generator, сценарії, сторінка керування

**Мета:** стенд сам створює навантаження із заданою інтенсивністю. Через API та сторінку керування вмикаються пʼять сценаріїв §6.6. SQL-зонд публікує метрики стану БД.

**Залежить від:** S2. Перевірка: `make e2e K=s02` зелений.

**Файли:**

- створити `services/common/bankmon_common/http.py`;
- створити `services/generator/Dockerfile`, `services/generator/requirements.txt`, `services/generator/bank_generator/{__init__,main,scenarios,state,engine,operations,probe,api,metrics}.py`, `services/generator/bank_generator/static/control.html`;
- створити `tests/unit/test_scenarios.py`, `tests/unit/test_state.py`, `tests/unit/test_pacing.py`, `tests/e2e/test_s03_generator.py`, `scripts/scenario.sh`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `Makefile`, `tests/requirements.txt`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **`bank_generator.scenarios`:** таблиця §6.6 як словник незмінних датакласів `Scenario(name, title_uk, description_uk, hot_accounts, big_amount_share, lock_order, lock_gap_ms, sleep_ms)`. `hot_accounts` — `None` або кількість перших `id`. Українські назви: «Звичайний режим», «Повільні запити», «Конкуренція за блокування», «Взаємні блокування», «Масові відмови».
2. **`bank_generator.state`:** потокобезпечний `ControlState` зі станом §6.7. Метод `apply(patch: dict, now: datetime) -> dict` валідує за правилами §6.7 і кидає `ValueError` з поясненням; метод `expire(now) -> bool` повертає стан у `normal`, якщо `expires_at` минув. Зміна `rate` чи `running` не скидає сценарій і його `expires_at`.
3. **`bank_generator.operations`** — чотири операції, кожна приймає зʼєднання й поточний сценарій:
   - `transfer`: два різні рахунки з пулу сценарію; сума — випадкова `1.00…500.00` з кроком `0.01`, а з імовірністю `big_amount_share` — `1000000.00`; публікація `TransferRequested` у `bank.transfers` із ключем `transfer.requested` та підтвердженням доставки (publisher confirms);
   - `balance_check`: `SELECT balance FROM accounts WHERE id = %s` для випадкового рахунку;
   - `statement`: останні 20 записів журналу випадкового рахунку з `LEFT JOIN transfers`, сортування за `created_at DESC`;
   - `deposit`: в одній транзакції знайти рахунок із найменшим балансом, додати йому `2000.00` (`UPDATE … updated_at = now()`) і записати `ledger_entries` з `kind = 'deposit'`.
4. **`bank_generator.engine`** — один потік:
   - власне зʼєднання з БД (`application_name = "bank-generator"`, `autocommit`) і з RabbitMQ; після підключення — `declare_topology` і перелік `id` рахунків;
   - вибір операції за вагами §6.6;
   - темп: наступний запуск = попередній + `1 / rate`. Якщо відставання перевищило 1 с — розклад починається з поточного моменту (без «наздоганяння» пачкою). Чисту функцію розрахунку винеси окремо — її покриває `test_pacing.py`;
   - `running = false` або `rate = 0` → простій із кроком 0,2 с; очікування тільки через `connection.sleep()` (G8);
   - на кожному кроці перевіряє `expire()`; якщо сценарій сплив — записує `normal` у `scenario_state` і пише `scenario_changed`;
   - помилка операції → `result="error"`, подія `operation_failed`; втрата зʼєднання → перепідключення з паузами (R9). Потік не завершується.
5. **Запис `scenario_state`.** Обробник `PUT` після успішного `apply` синхронно оновлює рядок `scenario_state` (окреме коротке зʼєднання) і лише тоді відповідає `200`. Під час запуску сервіс записує `normal`.
6. **`bank_generator.probe`** — окремий потік, кожні 5 с, зʼєднання за `MONITOR_DATABASE_URL` (`application_name = "bank-probe"`):
   - `bank_db_lock_waiters`: кількість сесій поточної бази з `wait_event_type = 'Lock'`;
   - `bank_db_longest_transaction_seconds`: вік найстаршої транзакції серед чужих сесій поточної бази, 0 якщо таких немає;
   - `bank_db_accounts_total_balance`: `SUM(balance)`;
   - `bank_db_probe_up`: 1 після вдалого опитування, 0 після невдалого (плюс подія `probe_failed` і перепідключення).
7. **`bankmon_common.http`:** `instrument_app(app)` — проміжний шар FastAPI з метриками HTTP §6.9 (`route` — шаблон маршруту; для невідомих шляхів — `unmatched`); `add_health_and_metrics(app)` — маршрути `/healthz` і `/metrics`. Запити до `/metrics` і `/healthz` у метрики HTTP не потрапляють.
8. **`bank_generator.api`:** маршрути §6.7. `GET /control/` віддає `control.html`. Журнал доступу uvicorn вимкнено.
9. **`control.html`** — один файл без зовнішніх ресурсів, українською:
   - заголовок «Керування навантаженням»;
   - блок стану, що оновлюється кожні 2 с: сценарій, інтенсивність, «працює / пауза», зворотний відлік до автоповернення;
   - пʼять кнопок сценаріїв із назвою, одним рядком опису та переліком очікуваних алертів (§11 спільної частини); активна кнопка виділена;
   - поле «Автоповернення через, с» (типово 120), яке застосовується до сценаріїв, відмінних від звичайного;
   - поле інтенсивності 0…200 з кнопкою «Застосувати»; кнопка «Пауза» / «Продовжити»;
   - посилання: `/grafana/d/bank-overview`, `/grafana/d/bank-db`, `/grafana/d/bank-app`, `/grafana/d/bank-queue`, `/grafana/d/bank-logs`, `/grafana/d/bank-traces`, `/prometheus/alerts`;
   - запити йдуть на відносний шлях `api/state`; помилка запиту показується на сторінці.
10. **`bank_generator.metrics`:** усі метрики `generator` із §6.9. `bank_scenario_active` виставляється для всіх пʼяти сценаріїв при кожній зміні.
11. **`bank_generator.main`:** `setup_logging`, запуск потоків `engine` і `probe`, uvicorn на `0.0.0.0:8000`. `SIGTERM` зупиняє потоки, код виходу 0.
12. **Сервіс `generator`:** збірка як у `worker`; змінні `DATABASE_URL`, `MONITOR_DATABASE_URL`, `AMQP_URL`, `GEN_RATE`; `depends_on` на `postgres`, `rabbitmq`, `worker` зі `service_healthy`; healthcheck `GET /healthz`.
13. **`scripts/scenario.sh <назва> [ttl]`** і ціль `make scenario NAME=… [TTL=…]`: виконує `PUT` до `generator` зсередини мережі (через `docker compose exec generator` засобами Python) і друкує новий стан. Назва не з переліку → помилка з переліком допустимих.
14. **`helpers.py`:** `control_get()`, `control_put(**fields)`, `rate_of(url, name, labels, window_s)` — приріст лічильника за вікно, поділений на його тривалість. **`conftest.py`:** фікстура рівня сесії тепер також чекає `GET /healthz` генератора й ставить `normal` на початку та в кінці; фікстура `scenario(name)` — як описано в §7; фікстура `paused_generator` ставить `running = false`, чекає спорожнення черги, а після тесту повертає `running = true`.
15. **Сервіс `tests`:** змінна `GENERATOR_URL=http://generator:8000`. У `tests/requirements.txt` — `fastapi`, `uvicorn`, `httpx`.

**Поза межами етапу:** авторизація (сторінка поки доступна без входу в dev-режимі), трейсинг, дашборди, зміни у `worker`.

**Acceptance criteria:**

- **S3-AC1.** При типових налаштуваннях швидкість `bank_generator_operations_total` (усі операції, `result="ok"`) за 20 с лежить у межах `GEN_RATE` ± 25 %; за 60 с кожна з чотирьох операцій має ненульовий лічильник; частка `transfer` — 60…80 %.
- **S3-AC2.** `PUT {"rate": 50}` → виміряна швидкість 50 ± 25 %. `PUT {"running": false}` → за наступні 5 с лічильник операцій зростає не більше ніж на 1; `bank_generator_running` = 0. `PUT {"running": true}` відновлює роботу.
- **S3-AC3.** Для кожного з пʼяти сценаріїв `PUT {"scenario": X}` повертає `200`, рядок `scenario_state` збігається з таблицею §6.6, `bank_scenario_active{scenario=X}` = 1, решта чотири = 0.
- **S3-AC4.** Невалідні тіла дають `422` і не змінюють стан: невідомий сценарій; `rate = -1`; `rate = 501`; `ttl_s = 3`; `ttl_s` разом із `scenario = "normal"`; `ttl_s` без `scenario`; невідоме поле.
- **S3-AC5.** `PUT {"scenario": "failures", "ttl_s": 5}`: у відповіді є `expires_at`; не пізніше ніж за 8 с `GET` повертає `normal` з `expires_at = null`, і рядок `scenario_state` — теж `normal`.
- **S3-AC6.** У сценарії `lock_contention` всі перекази, створені після перемикання (`requested_at` пізніший за момент `PUT`), мають обидва рахунки з `id` 1…3; у `deadlocks` — з 1…4.
- **S3-AC7.** У сценарії `failures` серед переказів, створених за 20 с після перемикання, частка `failed` — від 35 до 65 %.
- **S3-AC8.** З фікстурою `paused_generator` значення `bank_db_accounts_total_balance` не пізніше ніж за 10 с точно дорівнює `SELECT sum(balance) FROM accounts`; `bank_db_probe_up` = 1; `bank_db_lock_waiters` = 0.
- **S3-AC9.** `GET /control/` повертає `200`, `text/html`, містить «Керування навантаженням» і всі пʼять українських назв сценаріїв; жоден `src`, `href` чи `fetch` у файлі не веде на адресу з іменем хоста — тільки відносні шляхи та шляхи від кореня.
- **S3-AC10.** Сталий режим: 120 с при типових налаштуваннях — `messages_ready` черги `transfers.requested` жодного разу не перевищує 50; частка `failed` серед оброблених за цей час менша за 5 %; `check_invariants()` порожній.
- **S3-AC11.** Після `docker compose restart postgres` і після `docker compose restart rabbitmq` лічильник операцій знову зростає не пізніше ніж за 60 с; `RestartCount` контейнера `generator` дорівнює 0.
- **S3-AC12.** Після `docker compose restart generator` стан — `normal` з типовою інтенсивністю, рядок `scenario_state` — `normal`, навіть якщо перед перезапуском був увімкнений інший сценарій.
- **S3-AC13.** `scripts/check_json_logs.sh generator` друкує `JSON LOGS OK`; після зміни сценарію в логах є подія `scenario_changed` з полями `scenario` і `rate`.
- **S3-AC14.** `make scenario NAME=failures TTL=10` друкує стан зі сценарієм `failures`; `make scenario NAME=nope` завершується з помилкою.
- **S3-AC15.** `GET generator:8000/metrics` містить усі метрики `generator` з §6.9, `bank_build_info{service="generator"}` і `bank_http_requests_total` з міткою `route="/control/api/state"`.
- **S3-AC16.** Юніт-тести: таблиця сценаріїв збігається з §6.6 (значення перелічені в тесті явно); `ControlState.apply` — усі випадки `S3-AC4` і те, що зміна `rate` не скидає сценарій; `expire`; функція темпу — рівномірні інтервали й скидання розкладу після відставання.

**Перевірка:**

```bash
make up && docker compose ps
make lint unit e2e
docker compose restart postgres && sleep 10 && make e2e K=s03_ac1
docker compose restart rabbitmq && sleep 10 && make e2e K=s03_ac1
make scenario NAME=deadlocks TTL=30 && docker compose restart generator && make e2e K=s03_ac12
docker inspect -f '{{.RestartCount}}' "$(docker compose ps -q generator)"
scripts/check_json_logs.sh generator && scripts/check_json_logs.sh worker
make scenario NAME=failures TTL=10; make scenario NAME=nope; echo "exit=$?"
```

**Ручна перевірка:** `make up-dev`, відкрити `http://127.0.0.1:8002/control/`. Стан оновлюється сам; кнопка сценарію підсвічується; відлік автоповернення йде й сценарій повертається до звичайного; «Пауза» зупиняє лічильники; при ширині вікна 1280 і 390 пікселів нічого не вилазить за межі; у консолі браузера немає помилок.

---

## Етап S4 — Авторизація і gateway

**Мета:** єдиний відкритий порт. Усе за ним доступне тільки після входу; роль `admin` керує навантаженням, `viewer` — ні.

**Залежить від:** S3. Перевірка: `make e2e K=s03_ac1` зелений.

**Файли:**

- створити `services/auth/Dockerfile`, `services/auth/requirements.txt`, `services/auth/bank_auth/{__init__,main,api,users,security,metrics}.py`, `services/auth/bank_auth/templates/login.html`, `gateway/nginx.conf`;
- створити `tests/unit/test_auth_security.py`, `tests/unit/test_auth_users.py`, `tests/unit/test_auth_api.py`, `tests/e2e/test_s04_auth.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `tests/requirements.txt`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **`bank_auth.security`:**
   - `hash_password(password) -> str`, `verify_password(password, password_hash) -> bool` — bcrypt напряму (G16);
   - `issue_token(username, role, now=None) -> str`, `decode_token(token) -> dict | None` — HS256; невалідний, прострочений чи підписаний іншим ключем токен дає `None`, а не виняток; алгоритм при декодуванні зафіксовано списком `["HS256"]`;
   - `safe_redirect(rd: str | None) -> str` — правило `rd` із §6.8.
2. **`bank_auth.users`:** клас `UserStore(path)` на stdlib `sqlite3`: створює таблицю §6.8, якщо її немає; `get(username)`, `create(username, password, role)`, `ensure_seed(users) -> int` (створює лише відсутніх, повертає кількість створених). Кожна операція відкриває власне зʼєднання — так безпечно для потоків.
3. **`bank_auth.api`** — маршрути §6.8:
   - перевірка пароля для неіснуючого користувача теж виконує bcrypt (порівняння з наперед обчисленим хешем), щоб час відповіді не видавав, чи існує логін;
   - `POST /auth/login` з правильними даними: `303` на `safe_redirect(rd)`, cookie з параметрами §6.8; з неправильними: `401`, форма з текстом «Невірний логін або пароль», введений логін збережено в полі, cookie не встановлюється;
   - `GET /auth/verify`: токен із cookie або `Authorization: Bearer`; заголовки відповіді §6.8; `?require=admin` для ролі `viewer` → `403`;
   - пароль довший за 72 байти → `422` (G16);
   - події `login_succeeded` і `login_failed` (§6.11) та метрики §6.9. Пароль і токен ніколи не потрапляють у логи.
4. **`login.html`** — один файл без зовнішніх ресурсів, українською: «Вхід до BankMonitor», поля «Логін» і «Пароль», кнопка «Увійти», приховане поле `rd`.
5. **`bank_auth.main`:** `setup_logging`, `ensure_seed` з користувачами `AUTH_ADMIN_*` (роль `admin`) і `AUTH_VIEWER_*` (роль `viewer`), подія `users_seeded`, `instrument_app`, `add_health_and_metrics`, uvicorn на порту 8000. Якщо `AUTH_JWT_SECRET` коротший за 32 символи — сервіс не запускається й пояснює чому.
6. **Сервіс `auth`:** збірка як у `worker`; том `auth_data` у `/data`; змінні `AUTH_*`, `AUTH_DB_PATH`; healthcheck `GET /healthz`; процес не від root і має право запису в `/data`.
7. **`gateway/nginx.conf`:**
   - один `server` на порту 8080, `server_tokens off`, `client_max_body_size 1m`;
   - журнал доступу в stdout у JSON із полями §6.11 (`log_format … escape=json`); `user` — імʼя з відповіді `auth`;
   - два внутрішні (`internal`) розташування для підзапиту: звичайне (`/auth/verify`) та адміністративне (`/auth/verify?require=admin`), оформлені за G12;
   - маршрути §6.2, які вже мають upstream: `/healthz`, `/`, `/auth/login`, `/auth/logout`, `/auth/token`, `/auth/me`, `/control/`. Усе інше — `404`;
   - для сторінок: `401` → `302` на `/auth/login?rd=$request_uri`; для `/control/api/`: `401` → тіло `{"detail":"Not authenticated"}` з `Content-Type: application/json`;
   - до upstream завжди йдуть `X-Auth-User` і `X-Auth-Role`, узяті з відповіді `auth` (`auth_request_set`), тож клієнтські значення перезаписуються; `Host`, `X-Real-IP`, `X-Forwarded-For`, `X-Forwarded-Proto` передаються.
8. **Сервіс `gateway`:** образ із §3; конфіг змонтовано тільки для читання; `ports: ["${GATEWAY_PORT:-8080}:8080"]` — єдина секція `ports` у базовому файлі (R7); `depends_on` на `auth` і `generator` зі `service_healthy`; healthcheck `GET /healthz`.
9. **`helpers.py`:** `gateway()` — `requests.Session` з базовою адресою `GATEWAY_URL`, яка не йде за перенаправленнями; `login(username, password)` → сесія з cookie; `token(username, password)` → рядок токена.
10. **Сервіс `tests`:** змінні `GATEWAY_URL=http://gateway:8080`, `AUTH_URL=http://auth:8000` і всі `AUTH_*`. У `tests/requirements.txt` — `bcrypt`, `PyJWT`, `python-multipart`.

**Поза межами етапу:** реєстрація, зміна пароля, обмеження кількості спроб входу, HTTPS, маршрути `/grafana/` і `/prometheus/` (вони зʼявляться разом зі своїми сервісами), перевірка ролей усередині `generator`.

**Acceptance criteria:**

- **S4-AC1.** У базовому режимі `make check-ports` друкує `PORTS OK`: порт на хості має лише `gateway`.
- **S4-AC2.** `GET /healthz` → `200`. `GET /` → `302` з `Location: /grafana/`. `GET /nope` → `404`.
- **S4-AC3.** Без токена: `GET /control/` → `302`, `Location` починається з `/auth/login?rd=`, а розкодований `rd` дорівнює `/control/`. `GET /control/api/state` → `401`, тіло `{"detail":"Not authenticated"}`.
- **S4-AC4.** `POST /auth/login` з даними адміністратора та `rd=/control/` → `303` на `/control/`; cookie `bank_session` має `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age=3600`. З цією cookie `GET /control/` → `200`, `GET /control/api/state` → `200`.
- **S4-AC5.** Неправильний пароль і неіснуючий користувач → `401`, у тілі «Невірний логін або пароль», cookie немає; `bank_auth_logins_total{result="invalid_credentials"}` зростає; у логах `auth` є `login_failed` з цим логіном, а рядка з паролем немає.
- **S4-AC6.** `POST /auth/token` → токен, у якому `sub`, `role`, `exp - iat = AUTH_TOKEN_TTL_S`. З `Authorization: Bearer` `PUT /control/api/state` працює. `GET /auth/me` повертає імʼя й роль.
- **S4-AC7.** Роль `viewer`: `GET /control/` → `403`, `PUT /control/api/state` → `403`, стан не змінився.
- **S4-AC8.** Токен зі зміненим символом підпису, токен, підписаний іншим ключем, токен з `alg: none` і прострочений токен → `401` на `/control/api/state`.
- **S4-AC9.** `rd=https://evil.example`, `rd=//evil.example`, `rd=/\evil.example` і порожній `rd` після успішного входу дають `303` на `/grafana/`.
- **S4-AC10.** Запит без токена, але із заголовками `X-Auth-User: admin` і `X-Auth-Role: admin`, отримує `401` на `/control/api/state`. Запит `viewer` з тими самими заголовками — `403`.
- **S4-AC11.** `GET /auth/logout` → `303` на `/auth/login` і cookie з `Max-Age=0`; після цього `GET /control/` → `302`.
- **S4-AC12.** Через gateway недоступні: `/auth/verify`, `/auth/metrics`, `/auth/healthz`, `/metrics`, `/control/../metrics` — жоден не віддає `200` з метриками.
- **S4-AC13.** У файлі SQLite всі `password_hash` починаються з `$2`, паролів у відкритому вигляді немає. Після `docker compose restart auth` вхід працює, кількість користувачів — 2, подія `users_seeded` має `created = 0`.
- **S4-AC14.** `scripts/check_json_logs.sh auth` друкує `JSON LOGS OK`. Останні рядки логу `gateway` — JSON із полями §6.11, а в запитах після входу поле `user` — імʼя користувача.
- **S4-AC15.** Юніт-тести: хеш перевіряється правильним паролем і не перевіряється неправильним; два хеші одного пароля різні; усі випадки `S4-AC8` для `decode_token`; усі випадки `S4-AC9` для `safe_redirect`; `UserStore` на тимчасовому файлі — створення, унікальність логіна, `ensure_seed` не дублює й не змінює наявних; маршрути `bank_auth.api` через тестовий клієнт FastAPI, включно з `422` для пароля 73+ байти.
- **S4-AC16.** `nginx -t` у контейнері `gateway` — без помилок і попереджень. Усі тести попередніх етапів зелені (вони ходять повз gateway).

**Перевірка:**

```bash
make down && make up && docker compose ps
make check-ports
make lint unit e2e
docker compose exec gateway nginx -t
docker compose exec auth python -c "import sqlite3; print(sqlite3.connect('/data/auth.db').execute('select username, role, substr(password_hash,1,4) from users').fetchall())"
docker compose restart auth && sleep 5 && make e2e K=s04
scripts/check_json_logs.sh auth
docker compose logs gateway --no-log-prefix --tail 5
curl -si http://127.0.0.1:${GATEWAY_PORT:-8080}/control/ | head -5
```

**Ручна перевірка:** відкрити `http://127.0.0.1:8080/control/` у приватному вікні → форма входу українською. Неправильний пароль → повідомлення про помилку, логін лишився в полі. Вхід як `admin` → сторінка керування; кнопки працюють. Вийти (`/auth/logout`), увійти як `viewer` → `403`.
