# Скриншоти для звіту

Ширина вікна 1440 пікселів, світла тема, формат PNG. Перед знімками — `make up` і кілька хвилин роботи у звичайному режимі.

| Файл | Що на ньому | Як отримати |
|---|---|---|
| `01-login.png` | форма входу | у приватному вікні <http://localhost:8080/control/> |
| `02-control.png` | сторінка керування, звичайний режим | увійти `admin`, <http://localhost:8080/control/> |
| `03-overview-normal.png` | оглядовий дашборд, звичайний режим | <http://localhost:8080/grafana/d/bank-overview> |
| `04-postgresql.png` | дашборд «PostgreSQL» | <http://localhost:8080/grafana/d/bank-db> |
| `05-app.png` | дашборд «Застосунок: перекази» | <http://localhost:8080/grafana/d/bank-app> |
| `06-rabbitmq.png` | дашборд «RabbitMQ» | <http://localhost:8080/grafana/d/bank-queue> |
| `07-prometheus-targets.png` | сторінка цілей Prometheus | `admin`, <http://localhost:8080/prometheus/targets> |
| `08-prometheus-alerts.png` | сторінка правил, один алерт активний | `make scenario NAME=failures TTL=180`, через хвилину <http://localhost:8080/prometheus/alerts> |
| `09-overview-deadlocks.png` | оглядовий дашборд під час взаємних блокувань | `make scenario NAME=deadlocks TTL=180`, через хвилину огляд |
| `10-logs-deadlock.png` | дашборд «Логи» з рядками «deadlock detected» | під час того самого сценарію <http://localhost:8080/grafana/d/bank-logs> |
| `11-trace-transfer.png` | трейс переказу: generator → черга → worker → SQL | дашборд «Трейси» або Explore → Tempo, запит `{ name = "generator.transfer" }`, відкрити трейс |
| `12-trace-slow.png` | трейс із довгим спаном `pg_sleep` | `make scenario NAME=slow_queries TTL=120`, дашборд «Трейси» → «Повільні перекази» |
| `13-viewer-forbidden.png` | відповідь 403 для `viewer` на `/control/` | увійти `viewer`, <http://localhost:8080/control/> |
