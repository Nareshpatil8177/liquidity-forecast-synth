# Entity-Relationship Model

```mermaid
erDiagram
    LEGAL_ENTITY ||--o{ BANK_ACCOUNT : "owns (1:N)"
    LEGAL_ENTITY |o--o{ LEGAL_ENTITY : "parent (optional, self)"
    BANK_ACCOUNT ||--o{ LEDGER_ENTRY : "posts (1:N)"
    BANK_ACCOUNT ||--o{ DAILY_CASH_POSITION : "derived (1:N)"
    LEGAL_ENTITY ||--o{ RECEIVABLE : "bills"
    LEGAL_ENTITY ||--o{ PAYABLE : "owes"
    RECEIVABLE |o--|| CASH_FLOW_FORECAST : "1:1 optional"
    PAYABLE |o--|| CASH_FLOW_FORECAST : "1:1 optional"
    CASH_FLOW_FORECAST |o--o{ LEDGER_ENTRY : "settled by (0..N)"
    LIQUIDITY_SCENARIO ||--o{ SCENARIO_ASSUMPTION : documents
    LIQUIDITY_SCENARIO ||--o{ FORECAST_RUN : "applied in"
    FORECAST_RUN ||--o{ FORECAST_RUN_ITEM : "N:M bridge"
    CASH_FLOW_FORECAST ||--o{ FORECAST_RUN_ITEM : "N:M bridge"
    FORECAST_RUN ||--o{ FORECAST_RUN_ENTITY : "N:M bridge"
    LEGAL_ENTITY ||--o{ FORECAST_RUN_ENTITY : "N:M bridge"
    FORECAST_RUN ||--o{ FORECAST_DAILY_POSITION : projects
    FORECAST_RUN ||--o{ FORECAST_VS_ACTUAL : "explained by"
    FORECAST_RUN |o--o| FORECAST_RUN : "supersedes (version chain)"
    CURRENCY_RATE }o..o{ LEDGER_ENTRY : "joined by currency+date (logical)"
    STATE_EVENT }o..|| LEGAL_ENTITY : "append-only history (polymorphic)"
```

| Relationship | Cardinality | Optional? | Effective-dating / lifecycle |
|---|---|---|---|
| legal_entity -> bank_account | 1:N | no | account `opened_date` >= entity `effective_from`; closed entity closes its accounts |
| legal_entity -> legal_entity (parent) | N:1 | yes (holding has none) | parent id always lower than child (acyclic) |
| bank_account -> ledger_entry | 1:N | no | entries dated 2026-01-01 .. cutoff, none inside a freeze window |
| receivable / payable -> cash_flow_forecast | 1:1 | forecast item optional per doc | item created at invoice date; `revised_expected_date` effective from `revised_at` |
| cash_flow_forecast -> ledger_entry | 1:N | yes (unsettled items) | split payments give 2 entries |
| forecast_run <-> cash_flow_forecast | **N:M** via `forecast_run_item` | - | snapshot of date/amount/FX as known at the run cutoff |
| forecast_run <-> legal_entity | **N:M** via `forecast_run_entity` | - | closed/dormant entities recorded as excluded with a reason |
| liquidity_scenario -> forecast_run | 1:N | no | scenario parameters documented in `scenario_assumption` |
| forecast_run -> forecast_run (supersedes) | 1:1 | yes | re-run keeps old run; both stay in history |
| any lifecycle object -> state_event | 1:N | no | append-only; never updated |

## Lifecycles (see `state_event`)
- **legal_entity:** ACTIVE -> DORMANT | CLOSED
- **bank_account:** OPEN <-> FROZEN, OPEN|FROZEN -> CLOSED
- **receivable:** OPEN -> OVERDUE / PARTIALLY_PAID / PAID / CANCELLED / WRITTEN_OFF
- **payable:** same without WRITTEN_OFF
- **cash_flow_forecast:** SCHEDULED -> DELAYED / PARTIALLY_REALIZED / REALIZED / CANCELLED / WRITTEN_OFF
- **forecast_run:** CREATED -> CALCULATED -> (EXCEPTIONS_FLAGGED ->) APPROVED | REJECTED -> SUPERSEDED
