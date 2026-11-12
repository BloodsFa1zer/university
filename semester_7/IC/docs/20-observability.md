# Частина 2 — Спостережуваність (етапи S5–S8)

Застосунок уже працює й пише JSON-логи та метрики. Ці чотири етапи підключають до нього Prometheus, Grafana, Loki й Tempo і звʼязують три сигнали між собою.

**Спершу прочитай** `docs/00-common.md` повністю. Особливо важливі тут R4 (не вгадуй конфіги), §3 (де звіряти синтаксис), §6.9–§6.13 і граблі G2–G7, G10–G14, G19–G23.

**Про назви чужих метрик.** Контракт фіксує лише метрики з префіксом `bank_`. Назви метрик `postgres_exporter` і RabbitMQ нижче — очікувані. Якщо у зафіксованій версії назва інша, використай фактичну (знайди її через `curl …/metrics`), застосуй її скрізь, де вона згадується (правила, дашборди, тести), і запиши відповідність у журнал у розділ «Нотатки». Це не зміна контракту й не зупинка.

---

## Етап S5 — Prometheus і метрики БД

**Мета:** Prometheus збирає метрики PostgreSQL, RabbitMQ і трьох сервісів, зберігає їх у власній TSDB і обчислює сім правил алертів. Інтерфейс Prometheus доступний адміністратору через gateway.

**Залежить від:** S4. Перевірка: `make e2e K=s04` зелений, `make check-ports` друкує `PORTS OK`.

**Файли:**

- створити `observability/prometheus/prometheus.yml`, `observability/prometheus/rules/bank.yml`, `tests/e2e/test_s05_metrics.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `gateway/nginx.conf`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `postgres-exporter`:** образ із §3; підключається користувачем `MONITOR_DB_USER` до бази `bank` без TLS; увімкнений збирач `pg_stat_statements` (назву прапорця візьми з `--help`); `depends_on` на `postgres` зі `service_healthy`; healthcheck — за G2.
2. **Сервіс `prometheus`:** образ із §3; конфіг і правила змонтовані тільки для читання; том `prom_data` на каталог даних. Власний `command` замінює типові аргументи образу, тому всі потрібні прапорці задаються явно:
   - шлях до конфіга й каталогу даних;
   - зберігання 15 діб;
   - зовнішня адреса `http://localhost:${GATEWAY_PORT:-8080}/prometheus/` і префікс маршрутів `/` (щоб усередині мережі API лишався на `prometheus:9090/api/…`, а посилання в інтерфейсі вели на `/prometheus/…`);
   - зберігання exemplars (G10) — вмикається вже зараз, використовується з S8.
3. **`prometheus.yml`:** інтервал збору й обчислення правил 5 с; файл правил; шість завдань зі статичними цілями — `prometheus`, `postgres`, `rabbitmq` (шлях `/metrics/per-object`, G7), `generator`, `worker`, `auth`. Мітка `job` — саме ці назви (§6.9).
4. **`rules/bank.yml`:** група `bank` із сімома правилами §6.10 — назви, вирази й `for` дослівно; мітка `severity`; анотації `summary` і `description` українською, у `description` — підказка, який дашборд відкрити.
5. **Gateway:** маршрут `/prometheus/` тільки для ролі `admin`, префікс зрізається перед передачею до `prometheus:9090`. Сторінки без токена → `302` на вхід; `/prometheus/api/` без токена → `401` з JSON (§6.2).
6. **`helpers.py`:** `prom_query(expr, at=None) -> list[dict]` (миттєвий запит, повертає `result`); `prom_value(expr) -> float | None`; `alert_state(name) -> str` (`inactive` / `pending` / `firing` за `/api/v1/alerts` і `/api/v1/rules`); `wait_alert(name, state, timeout)`.
7. **`conftest.py`:** фікстура рівня сесії чекає ще й на готовність Prometheus (`/-/ready`).
8. **Сервіс `tests`:** змінна `PROM_URL=http://prometheus:9090`.
9. **Dev-режим:** порти 9090 і 9187 на `127.0.0.1`.

**Поза межами етапу:** Alertmanager, recording rules, Grafana, збір метрик Loki, Tempo, Alloy та Grafana (їхні завдання додають етапи S6–S8), зміна метрик сервісів.

**Acceptance criteria:**

- **S5-AC1.** `promtool check config` і `promtool check rules` у контейнері `prometheus` завершуються без помилок.
- **S5-AC2.** `up == 1` для всіх шести завдань; цілей у стані `down` немає; інтервал збору кожної цілі — 5 с.
- **S5-AC3.** Кожна з перелічених серій існує (запит повертає щонайменше одну серію):
  - PostgreSQL, з `datname="bank"` де це застосовно: `pg_up`, `pg_stat_database_xact_commit`, `pg_stat_database_xact_rollback`, `pg_stat_database_deadlocks`, `pg_stat_database_tup_inserted`, `pg_stat_database_tup_updated`, `pg_stat_database_tup_fetched`, `pg_stat_database_numbackends`, `pg_stat_database_blks_hit`, `pg_stat_database_blks_read`, `pg_locks_count`, `pg_stat_activity_count`, `pg_database_size_bytes`, `pg_settings_max_connections`, `pg_stat_user_tables_n_live_tup{relname="transfers"}`, і хоча б одна метрика з префіксом `pg_stat_statements_`;
  - RabbitMQ, з `queue="transfers.requested"`: `rabbitmq_queue_messages_ready`, `rabbitmq_queue_messages_unacked`, `rabbitmq_queue_consumers`;
  - усі метрики `bank_*` із §6.9 (крім лічильників із мітками, які ще не мали жодної події).
- **S5-AC4.** При типовому навантаженні: сума `rate(pg_stat_database_xact_commit{datname="bank"}[1m])` більша за 5; `rate` для `tup_inserted` і `tup_updated` більші за 0; `rabbitmq_queue_consumers{queue="transfers.requested"}` дорівнює `WORKER_CONCURRENCY`; `bank_db_accounts_total_balance` більша за 0.
- **S5-AC5.** `/api/v1/status/flags` показує зберігання 15 діб. Дані переживають перезапуск: зразок `up{job="worker"}`, записаний до `docker compose restart prometheus`, читається після нього запитом на той самий момент часу.
- **S5-AC6.** `/api/v1/rules` містить рівно сім алертів із назвами §6.10; кожен має мітку `severity` й анотації `summary` та `description`. Після того як усі алерти стали `inactive`, за 60 с спостереження в режимі `normal` жоден не переходить у `pending` чи `firing`.
- **S5-AC7.** Сценарій `failures`: `TransferFailureRatioHigh` стає `firing` не пізніше ніж за 120 с; після повернення в `normal` — `inactive` не пізніше ніж за 150 с.
- **S5-AC8.** Сценарій `deadlocks`: `DeadlocksDetected` стає `firing` не пізніше ніж за 120 с; після повернення в `normal` — `inactive` не пізніше ніж за 150 с.
- **S5-AC9.** Через gateway: `admin` — `GET /prometheus/api/v1/targets` → `200` з JSON; `viewer` → `403`; без токена `GET /prometheus/` → `302` на вхід, `GET /prometheus/api/v1/query?query=up` → `401` з JSON. Сторінка інтерфейсу для `admin` відкривається, і всі посилання на скрипти та стилі в її HTML починаються з `/prometheus/`.
- **S5-AC10.** `make check-ports` друкує `PORTS OK`; у dev-режимі порти 9090 і 9187 слухають тільки на `127.0.0.1`.
- **S5-AC11.** `docker compose config` показує, що рядок підключення експортера використовує `MONITOR_DB_USER`, а не адміністратора.

**Перевірка:**

```bash
make up && docker compose ps
docker compose exec prometheus promtool check config /etc/prometheus/prometheus.yml
docker compose exec prometheus promtool check rules /etc/prometheus/rules/bank.yml
make lint unit e2e
make check-ports
docker compose config | grep -n -i "data_source"
docker compose exec gateway nginx -t
```

**Ручна перевірка:** увійти як `admin`, відкрити `http://127.0.0.1:8080/prometheus/targets` — усі цілі зелені; `/prometheus/alerts` — сім правил. Увімкнути `make scenario NAME=failures TTL=90` і побачити, як `TransferFailureRatioHigh` стає жовтим, потім червоним, а після повернення — зеленим.

---

## Етап S6 — Grafana і дашборди

**Мета:** Grafana працює за `/grafana/` через auth proxy: користувач `auth` стає користувачем Grafana з відповідною роллю. Чотири дашборди показують стан БД, застосунку й черги.

**Залежить від:** S5. Перевірка: `make e2e K=s05_ac2` зелений.

**Файли:**

- створити `observability/grafana/provisioning/datasources/datasources.yml`, `observability/grafana/provisioning/dashboards/dashboards.yml`, `observability/grafana/dashboards/{bank-overview,bank-db,bank-app,bank-queue}.json`, `tests/e2e/test_s06_grafana.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `gateway/nginx.conf`, `observability/prometheus/prometheus.yml`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `grafana`:** образ із §3; том `grafana_data`; provisioning і дашборди змонтовані тільки для читання; healthcheck `GET /api/health` (за G2). Налаштування — змінними `GF_*` (назви звір із документацією версії, R4):
   - сервер: `root_url = http://localhost:${GATEWAY_PORT:-8080}/grafana/`, `serve_from_sub_path = true`;
   - auth proxy: увімкнено, заголовок `X-WEBAUTH-USER`, властивість `username`, автоматичне створення користувачів, роль із заголовка `X-WEBAUTH-ROLE`, синхронізація на кожен запит;
   - форма входу вимкнена; вихід веде на `/auth/logout`; самореєстрація вимкнена; анонімний доступ вимкнений;
   - внутрішній адміністратор — `GF_SECURITY_ADMIN_USER` і `GF_SECURITY_ADMIN_PASSWORD` з `.env` (ним користуються лише тести зсередини мережі);
   - надсилання статистики й перевірка оновлень вимкнені;
   - домашній дашборд — `bank-overview`. Його задає одноразовий сервіс `grafana-init` через API налаштувань організації (`PUT /api/org/preferences`), бо `default_home_dashboard_path` у Grafana 13 показує окрему копію, яку роль `Viewer` відкрити не може; `gateway` залежить від `grafana-init` з умовою `service_completed_successfully` (G17).
2. **`datasources.yml`:** джерело `Prometheus`, uid `prometheus`, адреса `http://prometheus:9090`, типове, інтервал збору 5 с, без можливості редагування з UI.
3. **`dashboards.yml`:** один постачальник типу «файл», тека «BankMonitor», редагування з UI й видалення заборонені, перечитування кожні 10 с.
4. **Загальні правила дашбордів** (G19):
   - `uid` і назва — з §6.13; `id` — `null`; тег `bankmonitor`; оновлення 5 с; діапазон — останні 15 хвилин; часовий пояс браузера;
   - джерело даних у кожній панелі задане через uid (`prometheus`), а не через назву чи змінну;
   - назви панелей — українською, у кожної часової панелі задана одиниця виміру;
   - вікно `rate` — `[1m]` або `$__rate_interval` (G14);
   - вираз для метрики, серії якої зʼявляються лише після першої події (`bank_worker_db_errors_total`, `bank_transfer_retries_total`, `bank_worker_messages_dead_lettered_total` тощо), закінчується на `or vector(0)`, щоб панель не показувала «No data»;
   - у кожному дашборді є посилання на решту за тегом `bankmonitor`.
5. **`bank-overview` — «BankMonitor — огляд».**
   - Рядок показників (stat): «Сервіси в роботі» (скільки цілей `up` із загальної кількості); «Транзакцій БД за секунду»; «Переказів за секунду»; «Частка відмов» (пороги 5 % і 20 %); «p95 обробки переказу» (пороги 0,1 і 0,5 с); «Черга переказів» (пороги 50 і 200); «Сесій чекають блокування»; «Взаємних блокувань за хвилину».
   - «Сценарій» — панель стану в часі (state timeline) за `bank_scenario_active == 1`.
   - «Активні алерти» — таблиця за `ALERTS{alertstate="firing"}` з колонками назви, важливості й часу.
   - Графіки: «Перекази за статусом»; «Час обробки: p50, p95, p99»; «Глибина черги»; «Блокування: очікування і взаємні блокування».
6. **`bank-db` — «PostgreSQL».** Панелі: «Зʼєднання за станом»; «Використання ліміту зʼєднань» (відсоток від `max_connections`); «Транзакції: підтверджені й відкочені»; «Рядки: вставлено, оновлено, прочитано»; «Взаємні блокування»; «Блокування за режимом»; «Сесії, що чекають блокування»; «Найдовша транзакція»; «Частка влучань у кеш»; «Розмір бази»; «Рядків у таблицях»; «Сума балансів»; «Найважчі запити» (таблиця з десяти записів за сумарним часом із `pg_stat_statements`).
7. **`bank-app` — «Застосунок: перекази».** Панелі: «Операції генератора за типом»; «Помилки операцій генератора»; «p95 тривалості операцій генератора»; «Перекази за статусом і причиною»; «Час обробки: p50, p95, p99»; «Час від заявки до завершення: p95»; «Повтори після взаємного блокування»; «Помилки БД за кодом SQLSTATE»; «Перекази в обробці»; «Відхилені повідомлення»; «Входи: успішні й невдалі»; «HTTP-запити за статусом».
8. **`bank-queue` — «RabbitMQ».** Панелі: «Повідомлення в чергах» (готові, за чергою); «Не підтверджені повідомлення»; «Споживачі»; «Опубліковано й оброблено за секунду» (за власними метриками `generator` і `worker`); «Мертві повідомлення» (черга `transfers.dead`).
9. **Gateway:** маршрут `/grafana/` для будь-якого автентифікованого користувача:
   - до Grafana йдуть `X-WEBAUTH-USER` (з `X-Auth-User`) і `X-WEBAUTH-ROLE` (з `X-Auth-Grafana-Role`), обидва — з відповіді `auth`;
   - заголовок `Authorization` у бік Grafana очищається, щоб ніхто не зміг скористатися внутрішнім адміністратором через gateway;
   - підтримка WebSocket для `/grafana/api/live/` (G11);
   - без токена — `302` на вхід.
10. **`prometheus.yml`:** додати завдання `grafana` (ціль `grafana:3000`, шлях `/grafana/metrics` або `/metrics` — перевір фактичний).
11. **`helpers.py`:** `grafana_api(path, method="GET", **kw)` — запит до `GRAFANA_URL` від імені внутрішнього адміністратора; `dashboard_files() -> dict[str, dict]` — прочитані JSON-файли дашбордів; `panel_exprs(dashboard) -> list[tuple[str, str]]` — пари «назва панелі, вираз» з підстановкою `$__rate_interval → 1m`, `$__interval → 15s`.
12. **Сервіс `tests`:** змінні `GRAFANA_URL=http://grafana:3000/grafana`, `GF_SECURITY_ADMIN_USER`, `GF_SECURITY_ADMIN_PASSWORD`. **`conftest.py`:** чекати на готовність Grafana.
13. **Dev-режим:** порт 3000 на `127.0.0.1`. Напряму Grafana не дає увійти (форма вимкнена) — користуйся gateway.

**Поза межами етапу:** джерела Loki й Tempo, дашборди логів і трейсів, алерти Grafana, плагіни, зміна метрик сервісів.

**Acceptance criteria:**

- **S6-AC1.** `grafana` у стані `healthy`; через gateway з cookie адміністратора `GET /grafana/api/health` → `200` і `"database": "ok"`.
- **S6-AC2.** Вхід як `viewer` через gateway: `GET /grafana/api/user` повертає логін `viewer`, роль в організації — `Viewer`; спроба зберегти дашборд (`POST /grafana/api/dashboards/db`) → `403`. Вхід як `admin`: логін `admin`, роль `Admin`.
- **S6-AC3.** Підробка: без токена, але із заголовком `X-WEBAUTH-USER: admin` → `302` на вхід. З cookie `viewer` і заголовками `X-WEBAUTH-USER: admin`, `X-WEBAUTH-ROLE: Admin` → Grafana все одно бачить `viewer` з роллю `Viewer`. З cookie `viewer` і `Authorization: Basic` внутрішнього адміністратора → теж `viewer`.
- **S6-AC4.** Джерело з uid `prometheus` існує, типове; перевірка стану джерела через API Grafana успішна.
- **S6-AC5.** У теці «BankMonitor» є чотири дашборди цього етапу з uid і назвами §6.13: `bank-overview`, `bank-db`, `bank-app`, `bank-queue`; домашній дашборд — `bank-overview`. (Тест перевіряє наявність саме цих чотирьох, а не загальну кількість: наступні етапи додають ще два.)
- **S6-AC6.** Кожен вираз кожної панелі з джерелом `prometheus` у кожному дашборді виконується в Prometheus без помилки й повертає непорожній результат при типовому навантаженні. Єдиний виняток — панель «Активні алерти».
- **S6-AC7.** Гігієна JSON кожного дашборда: `uid` як у §6.13; `id` — `null`; немає `__inputs` і `${DS_`; у кожної панелі є непорожня назва з кириличними літерами; джерело кожної панелі має uid `prometheus`; є тег `bankmonitor`; оновлення `5s`.
- **S6-AC8.** Усі панелі, перелічені у вимогах 5–8, присутні в відповідних дашбордах (тест порівнює множини назв).
- **S6-AC9.** `up{job="grafana"} == 1`.
- **S6-AC10.** `GET /grafana/d/bank-overview` через gateway для `viewer` → `200`; жодна відповідь Grafana на цьому шляху не перенаправляє за межі `/grafana/` чи `/auth/`.
- **S6-AC11** (візуальний). Під типовим навантаженням на кожному з чотирьох дашбордів немає панелей «No data» та позначок помилки; при ширині вікна 1440 пікселів панелі не накладаються; у консолі браузера немає помилок WebSocket.
- **S6-AC12.** `make check-ports` друкує `PORTS OK`; `docker compose exec gateway nginx -t` — без помилок.

**Перевірка:**

```bash
make up && docker compose ps
make lint unit e2e
make check-ports
docker compose exec gateway nginx -t
docker compose logs grafana --tail 100 | grep -i -E "provision|error" | tail -20
```

**Ручна перевірка:** `S6-AC11` — увійти як `viewer` на `http://127.0.0.1:8080/`, потрапити на оглядовий дашборд, переглянути всі чотири. Увімкнути сценарій `deadlocks` (як `admin` на `/control/`) і побачити зміну показників та панелі «Сценарій» на оглядовому дашборді.

---

## Етап S7 — Loki, Alloy і логи

**Мета:** логи всіх контейнерів стенда потрапляють у Loki з мітками `service`, `container`, `level`. У Grafana є джерело Loki та дашборд логів; у логах PostgreSQL видно повільні запити, очікування блокувань і помилки.

**Залежить від:** S6. Перевірка: `make e2e K=s06_ac5` зелений.

**Файли:**

- створити `observability/loki/loki.yml`, `observability/alloy/config.alloy`, `observability/grafana/dashboards/bank-logs.json`, `tests/e2e/test_s07_logs.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `observability/grafana/provisioning/datasources/datasources.yml`, `observability/prometheus/prometheus.yml`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `loki`:** образ із §3; один процес; том `loki_data`; конфіг тільки для читання. У `loki.yml`: автентифікація вимкнена; файлове сховище; актуальна для версії схема індексу; зберігання 7 діб з увімкненим видаленням старих даних; надсилання статистики вимкнене. Healthcheck — за G2.
2. **Сервіс `alloy`:** образ із §3; `config.alloy` тільки для читання; `/var/run/docker.sock` тільки для читання (G6); якщо сокет недоступний від типового користувача образу — запусти контейнер від root і поясни це коментарем у compose. Конвеєр у `config.alloy`:
   - виявлення контейнерів Docker з фільтром за міткою проєкту `bankmon`;
   - мітка `service` — з мітки compose-сервісу контейнера; мітка `container` — імʼя контейнера без початкової косої риски;
   - читання логів контейнерів;
   - обробка: для рядків, які є JSON із полем `level`, значення стає міткою `level`; рядки, що не є JSON, проходять без змін і без цієї мітки;
   - жодних інших міток (§6.11);
   - надсилання в `http://loki:3100`.
3. **`datasources.yml`:** джерело `Loki`, uid `loki`, адреса `http://loki:3100`.
4. **`bank-logs.json` — «Логи»** (правила з S6, вимога 4; джерело панелей — uid `loki`). Змінні: `service` (кілька значень, з міток Loki, типово всі), `search` (текстове поле, типово порожнє). Панелі:
   - «Обсяг логів за сервісами» — стовпчики за `service`;
   - «Помилки й попередження» — кількість рядків із `level` `error` і `warning` за сервісами;
   - «Логи сервісів» — потік рядків вибраних сервісів із фільтром `search`;
   - «PostgreSQL: повільні запити, блокування, помилки» — рядки `postgres`, що містять `duration:`, `still waiting for`, `deadlock detected` або `ERROR`;
   - «Невдалі входи» — події `login_failed` сервісу `auth`;
   - «Запити через gateway» — журнал доступу nginx.
5. **`prometheus.yml`:** додати завдання `loki` й `alloy`.
6. **`helpers.py`:** `loki_query(logql, since_s=300, limit=100) -> list[dict]` — запит діапазону, повертає рядки з міткою часу, мітками потоку й розібраним JSON (якщо рядок — JSON); `loki_labels() -> set[str]`; `wait_logs(logql, since_s, timeout, min_lines=1)`.
7. **Сервіс `tests`:** змінна `LOKI_URL=http://loki:3100`. **`conftest.py`:** чекати на готовність Loki.
8. **Dev-режим:** порти 3100 і 12345 на `127.0.0.1`.

**Поза межами етапу:** правила алертів у Loki, розбір логів PostgreSQL на поля, зміна формату логів сервісів, трейси та поле `trace_id`.

**Acceptance criteria:**

- **S7-AC1.** `GET loki:3100/ready` і `GET alloy:12345/-/ready` → `200`.
- **S7-AC2.** За останні 5 хвилин у Loki є рядки з кожною з міток `service`: `postgres`, `rabbitmq`, `worker`, `generator`, `auth`, `gateway`, `prometheus`, `grafana`.
- **S7-AC3.** Множина назв міток Loki не містить нічого, крім `service`, `container`, `level` і службових міток самого Loki. Значення `level` — лише з переліку `debug`, `info`, `warning`, `error`. У потоків `worker`, `generator`, `auth` мітка `level` є; у потоку `postgres` її немає.
- **S7-AC4.** `{service="worker"} | json | event="transfer_completed"` за останню хвилину повертає рядки з полями `transfer_id`, `amount`, `duration_ms`.
- **S7-AC5.** Свіжість: рядок `transfer_completed` для щойно опублікованого переказу з відомим `transfer_id` зʼявляється в Loki не пізніше ніж за 15 с.
- **S7-AC6.** Сценарій `slow_queries`: не пізніше ніж за 60 с `{service="postgres"} |= "duration:" |= "pg_sleep"` повертає рядки.
- **S7-AC7.** Сценарій `deadlocks`: не пізніше ніж за 120 с є рядки `{service="postgres"} |= "deadlock detected"` і `{service="worker"} | json | event="deadlock_retry"`.
- **S7-AC8.** Невдалий вхід з унікальним логіном `e2e-<випадкове>` і паролем-маркером: рядок `{service="auth"} | json | event="login_failed"` з цим логіном є в Loki; пошук пароля-маркера по всіх сервісах за останні 5 хвилин не повертає нічого.
- **S7-AC9.** `{service="gateway"} | json | status="200"` повертає рядки з полями `method`, `uri`, `request_time`.
- **S7-AC10.** Джерело з uid `loki` існує, перевірка стану через API Grafana успішна. Дашборд `bank-logs` є в теці «BankMonitor», відповідає гігієні `S6-AC7` (з uid джерела `loki`) і містить усі шість панелей. Кожен запит панелі з типовими значеннями змінних Loki виконує без помилки.
- **S7-AC11.** `GET loki:3100/config` показує зберігання 168 годин з увімкненим видаленням.
- **S7-AC12.** `up == 1` для завдань `loki` і `alloy`; `make check-ports` друкує `PORTS OK`.

**Перевірка:**

```bash
make up && docker compose ps
make lint unit e2e
make check-ports
docker compose logs alloy --tail 50 | grep -i -E "error|denied" ; echo "grep exit=$?"
docker compose logs loki --tail 50 | grep -i "error" ; echo "grep exit=$?"
```

**Ручна перевірка:** відкрити дашборд «Логи»; вибрати сервіс `worker`, ввести в пошук `transfer_failed`. Увімкнути `make scenario NAME=deadlocks TTL=60` і побачити записи `deadlock detected` у панелі PostgreSQL. В Explore виконати `{service="postgres"} |= "still waiting for"` під час сценарію `lock_contention`.

---

## Етап S8 — Tempo, OpenTelemetry і трейси

**Мета:** кожна операція залишає трейс. Переказ видно одним трейсом від генератора через чергу до SQL-запитів обробника. З графіка можна перейти до трейсу, з трейсу — до логів, з логу — до трейсу.

**Залежить від:** S7. Перевірка: `make e2e K=s07_ac4` зелений.

**Файли:**

- створити `observability/tempo/tempo.yml`, `services/common/bankmon_common/tracing.py`, `observability/grafana/dashboards/bank-traces.json`, `tests/unit/test_tracing.py`, `tests/e2e/test_s08_traces.py`;
- змінити `services/common/bankmon_common/{logging,http}.py`, `services/worker/requirements.txt`, `services/worker/bank_worker/{main,consumer,processor,metrics}.py`, `services/generator/requirements.txt`, `services/generator/bank_generator/{main,engine,operations}.py`, `services/auth/requirements.txt`, `services/auth/bank_auth/main.py`;
- змінити `docker-compose.yml`, `docker-compose.dev.yml`, `observability/grafana/provisioning/datasources/datasources.yml`, `observability/grafana/dashboards/{bank-overview,bank-app}.json`, `observability/prometheus/prometheus.yml`, `tests/requirements.txt`, `tests/e2e/helpers.py`, `tests/e2e/conftest.py`.

**Вимоги:**

1. **Сервіс `tempo`:** образ із §3; один процес; том `tempo_data`; конфіг тільки для читання. У `tempo.yml`: HTTP на 3200; приймач OTLP gRPC на `0.0.0.0:4317` (G3); локальне сховище; зберігання 48 годин; надсилання статистики вимкнене. Права на том — за G4. Healthcheck — за G2.
2. **`bankmon_common.tracing`:**

   ```python
   def init_tracing(service: str) -> bool: ...        # True, якщо трейсинг увімкнено
   def shutdown_tracing() -> None: ...
   def get_tracer(): ...
   def current_trace_ids() -> tuple[str, str] | None: ...   # (trace_id: 32 hex, span_id: 16 hex)
   ```

   - `init_tracing` нічого не робить і повертає `False`, якщо `OTEL_SDK_DISABLED=true` або не задано `OTEL_EXPORTER_OTLP_ENDPOINT`; повторний виклик безпечний;
   - ресурс і експорт — за §6.12; пакетна відправка спанів;
   - вмикає автоінструментацію `psycopg` і `pika`, якщо ці бібліотеки встановлені в сервісі;
   - `current_trace_ids` повертає `None` поза спаном або коли трейсинг вимкнено.
3. **`bankmon_common.logging`:** форматер додає `trace_id` і `span_id`, коли `current_trace_ids()` їх повертає.
4. **`bankmon_common.http`:** `instrument_app` вмикає автоінструментацію FastAPI, якщо трейсинг увімкнено; `/metrics` і `/healthz` не трасуються.
5. **Порядок запуску в усіх трьох сервісах** (G20): `setup_logging` → `init_tracing` → усе інше. Перед виходом процесу — `shutdown_tracing`.
6. **`generator`:** кожна операція виконується всередині спана `generator.<операція>` з атрибутами §6.12. `bank.amount` — рядок, номери рахунків — цілі числа.
7. **`worker`:**
   - обробка повідомлення — усередині спана `worker.process_transfer`, дочірнього до спана споживання (контекст приходить із заголовків повідомлення);
   - атрибути §6.12: `bank.attempts` — ціле число; `bank.status` і `bank.fail_reason` виставляються за результатом;
   - кожен повтор після взаємного блокування — подія `deadlock_retry` з атрибутом `attempt`;
   - статус спана — за правилом §6.12;
   - спостереження `bank_transfer_processing_seconds` передає exemplar `{"trace_id": …}`, коли є активний спан.
8. **Стійкість** (G21): недоступний Tempo не зупиняє й не сповільнює обробку; помилки експорту не засмічують лог частіше ніж раз на 30 с.
9. **Compose:** усі три Python-сервіси отримують `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317`. Залежності `depends_on` від `tempo` не додаються.
10. **`datasources.yml`:**
    - джерело `Tempo`, uid `tempo`, адреса `http://tempo:3200`, з переходом «трейс → логи» до джерела `loki` (фільтр за `trace_id`);
    - у джерела `loki` — похідне поле, що знаходить `trace_id` у JSON-рядку і веде до джерела `tempo`;
    - у джерела `prometheus` — призначення exemplars: мітка `trace_id` веде до джерела `tempo`.
    Назви ключів provisioning звір із документацією версії (R4).
11. **`bank-traces.json` — «Трейси»** (правила з S6, вимога 4; джерело — uid `tempo`). Панелі-таблиці з пошуком TraceQL за останні 15 хвилин:
    - «Повільні перекази» — `worker.process_transfer` довше 500 мс;
    - «Невдалі перекази» — `bank.status = "failed"`;
    - «Перекази з повторами» — `bank.attempts > 1`;
    - «Спани з помилками» — статус `error`;
    - текстова панель «Корисні запити TraceQL» з трьома запитами §11 спільної частини.
12. **`bank-overview` і `bank-app`:** на панелях «Час обробки: p50, p95, p99» увімкнено показ exemplars.
13. **`prometheus.yml`:** додати завдання `tempo`.
14. **`helpers.py`:** `tempo_search(traceql, since_s=300, limit=20) -> list[dict]`; `tempo_trace(trace_id) -> dict`; `trace_spans(trace) -> list[dict]` — плоский перелік спанів з полями `service`, `name`, `span_id`, `parent_span_id`, `duration_ms`, `status`, `attributes`, `events`; `wait_traces(traceql, since_s, timeout, min_traces=1)`.
15. **Сервіс `tests`:** змінна `TEMPO_URL=http://tempo:3200`. У `tests/requirements.txt` — пакети трейсингу з §3. **`conftest.py`:** чекати на готовність Tempo.
16. **Dev-режим:** порт 3200 на `127.0.0.1`.

**Поза межами етапу:** metrics-generator і граф сервісів, вибіркове збирання трейсів, трейсинг nginx і PostgreSQL, зміна бізнес-логіки сервісів.

**Acceptance criteria:**

- **S8-AC1.** `GET tempo:3200/ready` → `200`; `up{job="tempo"} == 1`.
- **S8-AC2.** Для переказу, створеного генератором щойно (береться `id` рядка `transfers`, обробленого за останні 10 с), пошук `{ span.bank.transfer_id = "<id>" }` не пізніше ніж за 30 с повертає рівно один трейс. У ньому: спани сервісів `generator` і `worker`; спани з назвами `generator.transfer` і `worker.process_transfer`; спан публікації та спан споживання повідомлення; щонайменше пʼять SQL-спанів під `worker.process_transfer`; `generator.transfer` є предком `worker.process_transfer`.
- **S8-AC3.** У спана `worker.process_transfer` з `S8-AC2` є атрибути `bank.transfer_id`, `bank.scenario`, `bank.lock_order`, `bank.status`, `bank.attempts`; `bank.attempts` — число. У `generator.transfer` — `bank.transfer_id`, `bank.from_account`, `bank.to_account`, `bank.amount`, `bank.scenario`.
- **S8-AC4.** Сценарій `failures`: `{ span.bank.status = "failed" && span.bank.fail_reason = "insufficient_funds" }` повертає трейси; у такому трейсі є SQL-спан зі статусом помилки, а `worker.process_transfer` має статус не `error`.
- **S8-AC5.** Сценарій `slow_queries`: `{ resource.service.name = "worker" && name = "worker.process_transfer" && duration > 700ms }` повертає трейси; у такому трейсі є SQL-спан, текст запиту якого містить `pg_sleep`, тривалістю не менше 700 мс.
- **S8-AC6.** Сценарій `deadlocks`: `{ span.bank.attempts > 1 }` повертає трейси; спан `worker.process_transfer` у такому трейсі має подію `deadlock_retry`.
- **S8-AC7.** Звʼязок логів і трейсів: рядок `transfer_completed` у Loki для переказу з `S8-AC2` містить `trace_id`, що дорівнює ідентифікатору знайденого трейсу, і `span_id` із 16 шістнадцяткових символів.
- **S8-AC8.** Через API Grafana: у джерела `loki` є похідне поле з посиланням на джерело `tempo`; у джерела `tempo` налаштовано перехід до джерела `loki`; у джерела `prometheus` є призначення exemplars із джерелом `tempo`. Перевірка стану джерела `tempo` успішна.
- **S8-AC9.** Exemplars: `/api/v1/query_exemplars` для `bank_transfer_processing_seconds_bucket` за останні 5 хвилин повертає щонайменше один exemplar з міткою `trace_id`, і трейс із цим ідентифікатором існує в Tempo.
- **S8-AC10.** Вхід через `/auth/token` залишає трейс сервісу `auth` (`{ resource.service.name = "auth" }`), а запити до `/metrics` і `/healthz` — ні.
- **S8-AC11.** При зупиненому `tempo` (`docker compose stop tempo`) тест `S2-AC2` зелений, а p95 обробки за хвилину не перевищує 0,1 с; після `docker compose start tempo` тест `S8-AC2` знову зелений.
- **S8-AC12.** Дашборд `bank-traces` є в теці «BankMonitor», відповідає гігієні `S6-AC7` (з uid джерела `tempo`), містить усі пʼять панелей. Кожен запит TraceQL панелей Tempo виконує без помилки.
- **S8-AC13.** Накладні витрати: при типовому навантаженні p95 обробки переказу лишається меншим за 0,1 с, алертів немає; `check_invariants()` порожній.
- **S8-AC14.** Юніт-тести: без `OTEL_EXPORTER_OTLP_ENDPOINT` і з `OTEL_SDK_DISABLED=true` `init_tracing` повертає `False`, а `current_trace_ids()` — `None`; усередині спана тестового провайдера рядок логу містить `trace_id` із 32 і `span_id` із 16 шістнадцяткових символів; поза спаном цих полів немає.
- **S8-AC15.** Усі тести попередніх етапів зелені; `scripts/check_json_logs.sh` для `worker`, `generator`, `auth` друкує `JSON LOGS OK`; `make check-ports` друкує `PORTS OK`.

**Перевірка:**

```bash
make up && docker compose ps
make lint unit e2e
docker compose exec worker python -c "import urllib.request as u; r=u.Request('http://127.0.0.1:8000/metrics', headers={'Accept':'application/openmetrics-text'}); print([l for l in u.urlopen(r).read().decode().splitlines() if 'trace_id' in l][:2])"
docker compose stop tempo && make e2e K=s02_ac2 && docker compose start tempo && make e2e K=s08_ac2
for s in worker generator auth; do scripts/check_json_logs.sh $s; done
make check-ports
```

**Ручна перевірка:** на дашборді «Застосунок: перекази» навести курсор на точку exemplar на графіку часу обробки й перейти до трейсу. У трейсі розгорнути `worker.process_transfer`, побачити SQL-спани, натиснути перехід до логів. В Explore (Loki) відкрити рядок `transfer_completed` і перейти за посиланням `trace_id` до Tempo. Увімкнути `slow_queries` і знайти довгий спан `pg_sleep` на дашборді «Трейси».
