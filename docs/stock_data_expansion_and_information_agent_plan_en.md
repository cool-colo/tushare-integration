# Stock Data Capability Expansion and Information Agent Plan

Document date: 2026-05-29  
Scope: `tushare-integration` data platform, quantitative research, backtesting, strategy generation, and investment information analysis.  
Objective: Provide management with an executable, phased, risk-aware plan.

---

## 1. Executive Summary

The current system already has a solid foundation around Tushare-based data ingestion, ClickHouse storage, DWD/DWS data layering, and data quality control. To better support higher-frequency strategy research, more reliable data governance, and systematic use of market-moving information, we need to expand capabilities in three relatively independent areas:

1. **Historical minute-level stock data and high-level data layers**
   - Expand from daily data to minute-level data, enabling intraday behavior research, event impact analysis, minute-level backtesting, and higher-frequency factor engineering.

2. **Multiple data sources and cross-source validation**
   - Move from a single Tushare source to a multi-source framework. Cross-source reconciliation, discrepancy monitoring, and trusted-source prioritization will reduce the impact of source errors, interface delays, and field definition changes.

3. **Information Agent for major market-moving information, structured reports, and strategy impact analysis**
   - Extend the system from structured market and financial data only to a combined framework of structured data and trusted information events. The Agent will collect news, announcements, research reports, and characteristic market data, generate professional reports, persist them to the database, and support AI analysis of their impact on trading strategies.

These three workstreams can be initiated, delivered, and evaluated independently. They can also share infrastructure such as source registration, scheduling, data quality control, metadata management, lineage tracking, and database storage standards. The recommended approach is to build core closed loops first, then expand coverage, avoiding overcommitment to all markets, all frequencies, and all information sources at the beginning.

---

## 2. Guiding Principles

- **Usable first, complete later**: Prioritize core A-share stocks, core fields, and core use cases. Expand frequency, market coverage, and source coverage after the first version is stable.
- **Land raw source data faithfully; unify business semantics later**: ODS stores raw data and ingestion metadata. DWD standardizes data. DWS/ADS provides stable views for research, backtesting, and strategy generation.
- **PIT and traceability first**: Any data used by training, backtesting, or strategy generation must answer what was visible at the time, where it came from, which batch wrote it, and whether it was later revised.
- **Quality gates before consumption**: New data must enter quality rules, cross-source reconciliation, and exception tracking before being used downstream.
- **Configurable and replaceable data sources**: Avoid hardcoding vendor logic into business code. Use a source registry and connector-style implementation to reduce future switching cost.
- **AI as decision support, not direct trading authority**: The Agent is responsible for information collection, summarization, structuring, impact hypotheses, and evidence organization. Strategy changes must still go through backtesting, risk control, and human approval.

---

## 3. Overall Roadmap

| Phase | Suggested Duration | Key Objective | Main Deliverables |
| --- | ---: | --- | --- |
| Phase 0: Research and Plan Confirmation | 2-3 weeks | Confirm data authorization, field scope, storage cost, priority stock universe, and information source whitelist | Data source inventory, interface feasibility assessment, field mapping draft, cost estimate |
| Phase 1: Minimum Viable Closed Loops | 6-8 weeks | Build MVP loops for minute-level data, multi-source validation, and the Information Agent | 1-minute/5-minute core market data tables, Tushare vs. second-source reconciliation, daily information report |
| Phase 2: Quality and Service Layer | 8-10 weeks | Establish DQC rules, discrepancy handling workflow, report persistence, and query services | DWD/DWS tables, quality rules, exception tables, report tables, API/SQL service views |
| Phase 3: Strategy Integration | 10-14 weeks | Integrate minute-level factors, source confidence, and information events into backtesting and model analysis | Strategy feature sets, event impact analysis, factor effectiveness evaluation, strategy impact reports |

> The overall plan should be managed as a 7-9 month program. The estimate assumes the current data platform foundation is available. Actual timing will mainly depend on data vendor procurement, API authorization, historical backfill scale, and vendor interface stability.

---

## 4. Workstream 1: Historical Minute-Level Stock Data and High-Level Data Layers

### 4.1 Why We Need It

The current system is mainly built around daily market data, financial data, capital flow, index data, and basic factors. Daily data is suitable for medium- and low-frequency research, but it cannot fully describe the following scenarios:

- Intraday price paths, trading rhythm, volume-price divergence, late-session rallies, opening shocks, and other minute-level behaviors.
- How quickly the market reacts to major news, announcements, or theme-driven narratives, and how that reaction persists or decays intraday.
- Finer-grained stop-loss, take-profit, slippage, capacity, and drawdown analysis.
- Minute-level or intraday aggregated factors such as VWAP deviation, opening strength, closing strength, intraday volatility, turnover concentration, and limit-up/limit-down behavior.
- Execution optimization for daily signals, such as selecting better entry times, reducing market impact, and filtering abnormal openings.

Without historical minute-level data, strategy research can only observe daily outcomes and cannot explain many execution differences and short-term market impacts seen in real trading.

### 4.2 Expected Outcomes

After implementation, the system should be able to:

- Persist historical A-share minute-level market data and support fast queries by stock, trading date, and time range.
- Provide unified and cleaned minute bars in the DWD layer, independent of any single vendor's naming convention.
- Produce minute-level high-level features in DWS, including intraday return, volatility, volume concentration, VWAP, opening and closing strength, abnormal turnover, and limit-up/limit-down behavior.
- Support minute-level backtesting, event impact analysis, intraday execution simulation, and execution optimization for daily signals.
- Aggregate minute-level features into daily samples and enrich the existing DWS factor wide table and model training sets.
- Link with the Information Agent to analyze price and volume reactions 5 minutes, 30 minutes, 1 day, and 3 days after specific information events.

### 4.3 Implementation Approach

#### 4.3.1 Data Scope

The recommended rollout has three steps:

| Stage | Stock Scope | Frequency Scope | Historical Scope | Purpose |
| --- | --- | --- | --- | --- |
| MVP | CSI 300, CSI 500, and selected core watchlist stocks | 1-minute or 5-minute | Last 1-2 years | Validate ingestion, storage, query performance, feature calculation, and cost |
| Expansion | All common A-shares, excluding long-suspended and complex delisted cases initially | 1-minute, 5-minute, 15-minute, 30-minute | Last 3-5 years | Support main research scenarios |
| Complete Coverage | All A-shares including historical delisted samples | 1-minute as the base; other intervals aggregated from 1-minute data | As complete as possible | Support rigorous backtesting and survivorship-bias control |

In the early stage, store 1-minute data as the base. Other intervals should be generated through DWS aggregation to avoid duplicate ingestion and storage.

#### 4.3.2 Data Layering

Follow the existing ODS/DWD/DWS design:

```text
External minute-level data source
  -> ODS raw minute market data
  -> DWD standardized minute bars
  -> DWS minute-level and intraday aggregated features
  -> ADS backtesting and strategy input views
```

Recommended new core tables:

| Layer | Suggested Table | Responsibility |
| --- | --- | --- |
| ODS | `ods_stock_minute_bar_raw` | Store raw source fields, raw payload, ingestion batch, source, and ingestion time |
| DWD | `dwd_stock_minute_bar` | Standardize stock code, trading time, interval, OHLCV, amount, adjustment flag, and source priority |
| DWS | `dws_stock_intraday_feature` | Calculate minute-level and intraday aggregated features |
| DWS | `dws_stock_event_reaction_minute` | Store minute-level reactions after information events |
| ADS | `ads_stock_intraday_factor_panel` | Provide stable access for research, backtesting, and model training |

#### 4.3.3 Core Fields

`dwd_stock_minute_bar` should include at least:

| Field | Description |
| --- | --- |
| `instrument_id` | Internal unified security ID |
| `ts_code` | Source-side stock code |
| `trade_date` | Trading date |
| `trade_datetime` | Minute timestamp |
| `bar_interval` | Interval, such as `1m` or `5m` |
| `open` / `high` / `low` / `close` | Minute OHLC prices |
| `volume` | Trading volume |
| `amount` | Trading amount |
| `vwap` | Minute VWAP, derived from amount and volume |
| `source` | Data source |
| `source_priority` | Priority of the adopted source |
| `batch_id` | Ingestion batch |
| `ingest_time` | Ingestion time |
| `record_hash` | Row content hash for revision detection |
| `is_suspended` | Whether the stock was suspended or had no trade |

#### 4.3.4 High-Level Features

The first DWS feature set should focus on explainable, backtestable, and cost-controlled indicators:

| Category | Feature Examples | Use Case |
| --- | --- | --- |
| Intraday return | Return over first 5/15/30 minutes, return over last 30 minutes | Capture opening shocks and closing-session fund behavior |
| Intraday volatility | Standard deviation of minute returns, high-low range, upside/downside volatility | Measure short-term risk and crowding |
| Trading structure | Share of turnover in first 30 minutes, closing-session turnover share, turnover concentration | Identify when capital enters |
| VWAP deviation | Close-to-VWAP and open-to-VWAP deviation | Improve execution and identify strength or weakness |
| Liquidity | Median minute turnover, low-turnover minute ratio | Evaluate capacity and slippage risk |
| Limit behavior | First limit-touch time, limit-seal duration, number of break-limit events | Support limit-up/limit-down and theme strategies |
| Event reaction | Return and turnover expansion 5/30/60 minutes after information release | Connect the Information Agent with price impact analysis |

#### 4.3.5 Data Quality Rules

New DQC rules should cover:

- Uniqueness: `instrument_id + trade_datetime + bar_interval + source` must be unique.
- Completeness: The number of minute bars in a trading day must match the trading calendar and trading session rules.
- OHLC consistency: `low <= open/close <= high`.
- Nonnegative values: Volume and amount must be nonnegative.
- Price validity: If there is trading volume, prices must be positive.
- Time validity: Minute timestamps must fall within valid trading sessions.
- Cross-interval consistency: 5-minute and 15-minute bars should be consistent with aggregation from 1-minute bars.
- Daily consistency: Daily OHLCV aggregated from minute bars should match daily market data within tolerance.

#### 4.3.6 Technical Implementation Notes

- Use ClickHouse as the primary storage engine, partitioned by `trade_date` and ordered by `instrument_id, trade_datetime`.
- Separate historical backfill from daily incremental jobs so historical tasks do not affect daily SLA.
- Use batched writes and idempotent upsert logic to prevent duplicate backfill inflation.
- Retain `source`, `batch_id`, `ingest_time`, and `record_hash` in all minute-level tables to support cross-source validation and revision tracking.
- Prefer SQL-reproducible feature pipelines first. Introduce Python or UDF logic only for more complex features.

### 4.4 Implementation Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Large minute-level data volume | Higher storage cost, longer backfill time, and query pressure | Start with core stock universe MVP; partition by date; use hot/cold storage; store only 1-minute bars and aggregate other intervals |
| Data authorization restrictions | Some vendors may restrict historical minute data, bulk download, or commercial use | Complete authorization review in Phase 0; confirm API rate limits, historical coverage, and storage rights before procurement |
| Source definition differences | Vendors may differ on volume units, adjustment method, and suspended-minute handling | Standardize in DWD; retain source fields; establish cross-source discrepancy rules |
| Unstable backfill jobs | Large historical pulls may fail or hit limits | Support resumable backfill, task sharding, retry logic, and progress tracking |
| Inconsistency with daily data | Can reduce confidence in strategy research and backtesting | Add DQC rules comparing minute-aggregated daily data with daily source data |
| Premature high-frequency complexity | Increases cost and operational complexity | Phase 1 should support minute-level research and execution optimization only; do not commit to tick-level or low-latency trading |

---

## 5. Workstream 2: Multiple Data Sources and Cross-Source Validation

### 5.1 Why We Need It

Tushare is currently the only data source. A single-source setup is efficient in the early stage, but it creates long-term risks:

- A single interface failure, delay, field change, or permission change can directly affect downstream research and production strategies.
- Source data may contain revisions, omissions, unit changes, or outliers. A single source cannot independently prove correctness.
- Errors in critical fields such as market data, adjustment factors, financial announcements, share capital, suspensions, limit prices, and index constituents can directly affect factor calculation, backtesting, and live signals.
- When strategy results are abnormal, it is difficult to determine whether the cause is market change, model issue, or data issue without a second source.
- Minute-level data, research reports, news, and characteristic datasets will naturally create a multi-source environment. The framework should be established early.

Multi-source integration is not simply about buying more data. Its main purpose is to build data confidence, stability, and auditability.

### 5.2 Expected Outcomes

After implementation, the system should be able to:

- Support at least one data source in addition to Tushare, and remain extensible to sources such as Wind, Choice, iFinD, exchange data, CNINFO, Gildata, and CSMAR.
- Reconcile critical datasets across sources, including market data, adjustment factors, trading calendar, security master data, financial indicators, announcement events, and minute-level bars.
- Classify discrepancies into acceptable differences, warning-level differences, and blocker-level differences.
- Provide downstream users with trusted master views instead of requiring researchers to manually decide which source to use.
- Fall back to a backup source or delay publication when a source is abnormal, while recording the reason.
- Establish vendor quality metrics, including coverage, latency, missing rate, abnormal rate, revision frequency, and discrepancy rate.

### 5.3 Implementation Approach

#### 5.3.1 Data Source Tiers

Classify data sources into three tiers:

| Tier | Type | Examples | Usage |
| --- | --- | --- | --- |
| S | Official or statutory disclosure sources | Stock exchanges, CNINFO, listed company announcements, regulators | Authoritative sources for announcements, disclosures, trading rules, and security status |
| A | Professional financial data vendors | Tushare, Wind, Choice, iFinD, Gildata, CSMAR | Structured market data, financials, factors, research reports, macro, and industry data |
| B | Characteristic and widely used investor sources | Kai Pan La, CLS, East Money, Tonghuashun characteristic rankings | Sentiment, themes, heat, tags, and market narrative supplements |

S/A sources should be the main basis for validation. B-tier sources should be used as supplementary information and features, not as the sole basis for factual assertions.

#### 5.3.2 Connector Framework

Add a unified source integration framework:

```text
source_registry.yaml
  -> connector plugins
  -> ODS raw storage
  -> DWD standardized mapping
  -> DQC single-source quality checks
  -> cross_source_validation
  -> trusted views
```

Recommended `source_registry.yaml` structure:

```yaml
sources:
  tushare:
    type: vendor_api
    priority: 50
    enabled: true
    domains: [eod_price, finance, basic, moneyflow]
  exchange_sse:
    type: official_web_or_api
    priority: 100
    enabled: true
    domains: [announcement, trading_calendar, security_status]
  cninfo:
    type: official_disclosure
    priority: 100
    enabled: true
    domains: [announcement, corporate_action]
```

#### 5.3.3 Cross-Source Validation Scope

The first batch should cover datasets that are most important and most likely to affect strategy outcomes:

| Data Domain | Validation Target | Validation Method | Priority |
| --- | --- | --- | --- |
| Trading calendar | Trading days, holidays, special trading days | Set consistency | High |
| Security master | Code, short name, listing date, delisting date, exchange, status | Key and field consistency | High |
| Daily market data | OHLCV, amount, return | Exact or tolerance-based validation | High |
| Adjustment factors | Adjustment factor and dividend/split impact | Change-point validation | High |
| Limit prices and status | Limit price, limit-up status, consecutive limit-up information | Field consistency and rule recalculation | High |
| Financial announcements | Reporting period, announcement date, revision time | PIT visibility validation | High |
| Share capital and corporate actions | Total shares, float shares, dividends, placements, buybacks | Event-chain consistency | Medium-high |
| Minute-level bars | Minute OHLCV and daily aggregation | Tolerance-based validation | Medium-high |
| Characteristic data | Themes, rankings, fund behavior | Coverage and directional consistency | Medium |

#### 5.3.4 Discrepancy Handling

Recommended discrepancy tables and workflow:

| Suggested Table | Description |
| --- | --- |
| `dq_cross_source_run` | Run record for each cross-source validation job |
| `dq_cross_source_result` | Aggregated result by domain, source pair, discrepancy rate, and severity |
| `dq_cross_source_diff` | Detail-level differences, including key, field, source A value, source B value, and discrepancy type |
| `dq_source_quality_metric` | Long-term source metrics such as coverage, latency, abnormal rate, and discrepancy rate |
| `dwd_source_resolution_rule` | Main source, backup source, and conflict resolution rules by data domain |

Suggested discrepancy severity:

| Severity | Description | Handling |
| --- | --- | --- |
| BLOCKER | Major differences affecting trading calendar, security keys, core price fields, or PIT visibility | Block publication or publish in degraded mode |
| WARN | Differences that may not affect core strategies, such as small amount discrepancies outside tolerance | Publish with alert and enter follow-up queue |
| MONITOR | Used for long-term observation, such as characteristic tag coverage differences | Record trend, do not block |

#### 5.3.5 Trusted Views

Downstream users should not consume multiple raw source tables directly. They should access trusted views:

```text
Multiple DWD standardized source tables
  -> source_resolution_rule
  -> trusted DWD/DWS view
  -> research, backtesting, strategy, and AI analysis
```

Trusted views should clearly indicate:

- Which source each field comes from.
- Whether the field has passed cross-source validation.
- Which resolution rule was applied if there was a discrepancy.
- Whether any degradation or exception flag exists.

### 5.4 Implementation Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Long procurement and authorization cycle | The project may not be able to integrate a second source immediately | Run business procurement and technical PoC in parallel during Phase 0; prioritize existing authorized or trial sources |
| Different source definitions | False discrepancies may appear because definitions differ | Establish field dictionary, unit conversion, adjustment-method documentation, and tolerance rules |
| Overly strict validation | May generate many false alarms and disrupt daily publication | Start with `warn_only` mode to build baselines, then gradually move selected rules to `strict` |
| Vendor API rate limits | Large reconciliation and backfill jobs may hit limits | Prefer batch APIs; cache raw results; shard by domain and date |
| Unclear conflict ownership | Discrepancies may not be resolved, weakening trusted views | Define owner, main source, backup source, and blocker rules for each data domain |
| Higher cost | Multiple vendors and storage duplication increase cost | Cover critical domains first; avoid full duplication unless the quality benefit is justified |

---

## 6. Workstream 3: Information Agent for Major Information, Structured Reports, and Strategy Impact Analysis

### 6.1 Why We Need It

Stock prices are affected not only by historical market and financial data, but also by major information events, including policy changes, industry events, company announcements, research views, order wins, mergers and acquisitions, regulatory penalties, earnings guidance, market themes, capital preference, and investor attention.

If the current system only uses structured market and financial data, it has several limitations:

- It cannot quickly identify external information that drives price movement.
- It cannot structurally persist news, announcements, research reports, themes, and characteristic data, making later impact review difficult.
- Researchers rely on manual reading, which is inefficient, inconsistent, and weak in traceability.
- AI cannot systematically learn whether certain information types have stable effects on specific industries, stocks, or strategy factors.
- When strategies produce abnormal gains or losses, the system lacks information-level evidence for explanation.

We therefore need a configurable Information Agent that connects trusted information collection, structuring, report generation, persistence, and strategy impact analysis into a closed loop.

### 6.2 Expected Outcomes

After implementation, the system should be able to:

- Collect configurable categories of information, including news, announcements, research reports, policy updates, industry events, and characteristic market data such as Kai Pan La's "What to Trade Tomorrow".
- Configure, disable, and tier data sources, prioritizing credible, well-known sources that are widely used by investors.
- Automatically deduplicate content, identify entities, classify events, infer sentiment or impact direction, extract evidence, and score importance.
- Generate professional, structured, and traceable daily or intraday information reports.
- Provide a comprehensive investment reference summary at the end of each report, including key market conflicts, potentially benefited or harmed directions, uncertainties, and signals requiring follow-up.
- Persist all raw information, structured events, generated reports, cited evidence, and model outputs to the database.
- Enable AI and research modules to analyze whether such information affects trading strategies, for example by improving returns, increasing volatility, changing position risk, triggering risk controls, or changing stock rankings.

### 6.3 Implementation Approach

#### 6.3.1 Information Categories

Information categories must be configurable. The first batch should cover:

| Category | Examples | Main Use |
| --- | --- | --- |
| Company announcements | Earnings guidance, major contracts, M&A, share reduction, buybacks, penalties, litigation, guarantees | Identify company-level events |
| Financial news | Macro policy, regulatory updates, industry events, listed company news | Identify market narratives and external shocks |
| Research views | Broker research, rating changes, earnings forecast revisions, industry deep dives | Identify institutional expectation changes |
| Characteristic data | Kai Pan La "What to Trade Tomorrow", theme heat, limit-up hierarchy, capital preference | Capture short-term themes and sentiment |
| Market anomalies | Dragon-tiger list, limit-up/limit-down, volume surges, abnormal movement announcements | Explain price behavior |
| Sentiment and attention | Search heat, investor relations platforms, investor Q&A, news repost heat | Identify attention changes |

#### 6.3.2 Data Source Selection Principles

A source must be evaluated before entering the whitelist:

- Whether it has a clear operating entity, stable domain, and continuous operating record.
- Whether it is an official disclosure platform, professional financial data vendor, mainstream financial media outlet, or a data tool widely used by investors.
- Whether automated collection, API calls, internal storage, and secondary analysis are allowed.
- Whether it provides traceable fields such as publication time, original link, unique ID, security code, and industry tags.
- Whether it supports stable incremental updates instead of manual browsing only.

Candidate source tiers:

| Tier | Candidate Sources | Main Information |
| --- | --- | --- |
| S | Shanghai Stock Exchange, Shenzhen Stock Exchange, Beijing Stock Exchange, CNINFO, CSRC, NAFMII, etc. | Official announcements, regulatory information, rule changes |
| A | Wind, Choice, iFinD, Tushare Pro, Gildata, CSMAR | Structured news, announcements, research reports, financials, market data |
| A | CLS, China Securities Journal, Securities Times, Shanghai Securities News, etc. | Flash news, deep reports, policy and industry information |
| B | Kai Pan La, East Money, Tonghuashun characteristic data, Xueqiu, etc. | Themes, heat, short-term sentiment, investor attention |

B-tier data should only be used as market sentiment and characteristic feature input. It should not be the sole basis for factual judgments. Facts involving announcements, financials, regulatory penalties, or major contracts should be confirmed through S-tier or A-tier sources.

#### 6.3.3 Agent Architecture

Recommended architecture:

```text
source_config.yaml
  -> crawler / API connector
  -> raw information store
  -> deduplication and normalization
  -> entity linking
  -> event classification
  -> credibility scoring
  -> impact hypothesis generation
  -> structured report generation
  -> database persistence
  -> strategy impact analysis
```

Module responsibilities:

| Module | Responsibility |
| --- | --- |
| Source Registry | Manage sources, categories, permissions, frequency, priority, and enable/disable status |
| Collector | Collect raw information through APIs, RSS, authorized interfaces, or compliant crawlers |
| Normalizer | Standardize title, body, publication time, source, security code, industry, link, and content hash |
| Deduplicator | Deduplicate and aggregate by title, content hash, source ID, and similarity |
| Entity Linker | Link information to stocks, indices, industries, concepts, people, institutions, and regions |
| Event Classifier | Classify information as policy, announcement, research, order win, penalty, M&A, earnings, theme, etc. |
| Scorer | Score credibility, importance, timeliness, price impact likelihood, and uncertainty |
| Report Writer | Generate structured daily reports, intraday briefings, or topic reports |
| Persistence | Persist raw content, events, reports, cited evidence, and model outputs |
| Impact Analyzer | Connect events with market data, minute-level reactions, holdings, backtests, and strategy performance |

#### 6.3.4 Database Design

Recommended new tables:

| Suggested Table | Description |
| --- | --- |
| `ods_information_item_raw` | Raw news, announcements, research reports, and characteristic data, including raw content and ingestion metadata |
| `dwd_information_event` | Standardized event table, including event type, related instruments, publication time, source, and credibility |
| `dwd_information_entity_link` | Relationships between information items and stocks, industries, concepts, institutions, and other entities |
| `dws_information_impact_signal` | Event impact signals, including direction, strength, time horizon, and confidence |
| `ads_information_daily_report` | Daily structured reports and summaries |
| `ads_information_strategy_impact` | Association analysis between information events and strategy return, drawdown, turnover, and position changes |

Recommended core fields:

| Field | Description |
| --- | --- |
| `source` | Information source |
| `source_level` | S/A/B level |
| `source_item_id` | Source-side unique ID |
| `publish_time` | Publication time |
| `crawl_time` | System collection time |
| `available_time` | Time when the item becomes available to the system |
| `title` | Title |
| `content_hash` | Content hash |
| `raw_content` | Original content or body text within authorization scope |
| `summary` | Summary |
| `event_type` | Event type |
| `related_instruments` | Related stocks |
| `related_industries` | Related industries |
| `impact_direction` | Positive, negative, neutral, or uncertain |
| `impact_horizon` | Impact horizon, such as intraday, 1d, 3d, or 20d |
| `importance_score` | Importance score |
| `confidence_score` | Confidence score |
| `evidence` | Supporting evidence snippets or citation IDs |
| `model_version` | Model version used for report generation or classification |

#### 6.3.5 Report Structure

Daily information reports should follow a stable structure so they are readable, comparable, and database-friendly:

```text
1. Core conclusions of the day
2. Market main themes and risk appetite
3. Major macro and policy information
4. Industry and theme opportunities
5. Major company-level events
6. Research and institutional view changes
7. Characteristic data observations
8. Key stock and industry impact list
9. Potential relationship with existing strategies
10. Risks, uncertainties, and items requiring validation
11. Investment reference summary
```

The final summary must:

- Clearly distinguish facts, inferences, and uncertainties.
- Provide impact direction and expected horizon instead of generic commentary.
- Mark the most important evidence sources and conflicting information.
- Indicate which conclusions require follow-up validation through price, turnover, capital flow, or announcements.
- Avoid giving trading instructions that have not passed backtesting and risk-control validation.

#### 6.3.6 Strategy Impact Analysis

After information is persisted, AI and research modules can analyze:

- Return, turnover, volatility, and turnover-rate changes over `5m/30m/1d/3d/20d` after an event.
- Average impact of specific event types across industries, market-cap groups, and style groups.
- Whether certain information types strengthen or weaken existing factors such as momentum, reversal, capital flow, valuation, or earnings expectations.
- Whether information events explain abnormal strategy gains, losses, drawdowns, or concentration risk.
- Whether information features can be used as model candidate features, subject to out-of-sample testing and strict backtesting.

### 6.4 Implementation Risks

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Information source authorization and copyright restrictions | Original content storage, summarization, and secondary analysis may be restricted | Prefer APIs and authorized sources; define storage scope; store only metadata, summaries, and citation IDs where needed |
| Crawler compliance risk | Unauthorized scraping may violate site terms or lead to blocking | Use authorized interfaces, RSS, and public APIs; follow robots rules and rate limits; retain compliance records |
| High information noise | The Agent may output large amounts of low-value information | Use source tiers, deduplication, importance scoring, and whitelist categories |
| LLM hallucination or over-inference | Report conclusions may be unreliable | Require evidence citations; distinguish facts and inferences; add human review for critical reports; retain model versions |
| Entity linking errors | News may be linked to the wrong stock or industry | Use security master data, alias tables, rules, and confidence thresholds |
| Time visibility errors | Backtests may accidentally use future information | Store `publish_time`, `crawl_time`, and `available_time`; strategy analysis must use only information visible at the time |
| Instability of characteristic data | Sources such as Kai Pan La may change fields, pages, or authorization terms | Keep connectors modular; retain alternative sources; treat characteristic data as B-tier input only |
| Misuse of reports as trading instructions | Could bypass strategy validation and risk control | Position reports as investment references and strategy analysis inputs; strategy changes must pass backtesting and approval |

---

## 7. Relationship and Boundaries Across the Three Workstreams

The three workstreams are independent, but they will create long-term synergy:

| Workstream | Independent Value | Synergy With Other Workstreams |
| --- | --- | --- |
| Minute-level data | Provides finer-grained market data, execution analysis, and intraday factor capability | Supports event reaction analysis for the Information Agent; adds minute-level domain to multi-source validation |
| Multi-source validation | Improves data trustworthiness and production stability | Provides source priority, discrepancy handling, and quality metrics for minute-level and information data |
| Information Agent | Adds unstructured information and event explanation capability | Requires minute-level data to measure impact; requires multi-source framework to ensure information credibility |

Recommended boundaries:

- The minute-level data project is not responsible for procuring all external information sources, but it should support event reaction tables.
- The multi-source validation project is not responsible for explaining market logic. It is responsible for data trustworthiness and discrepancy governance.
- The Information Agent is not responsible for direct order generation or strategy replacement. It is responsible for information structuring, report generation, and strategy impact analysis input.

---

## 8. Priority Recommendation

Recommended priority by risk-adjusted value:

1. **Prioritize the multi-source validation foundation**
   - Reason: Minute-level data and the Information Agent will both rely on source registration, lineage, quality rules, and trusted views.

2. **Run the minute-level data MVP in parallel**
   - Reason: Minute-level data has high value for strategy research and event impact analysis, but has material data volume and authorization risk. Cost should be validated early.

3. **Start the Information Agent daily report MVP**
   - Reason: Start with a small number of high-trust sources to build a closed loop for structured daily reports and persistence, then gradually add research reports, characteristic data, and strategy impact analysis.

Phase 1 should not include:

- Building a tick-level data platform.
- Integrating a large number of low-trust websites at once.
- Allowing the Agent to directly generate trading instructions.
- Treating all source discrepancies as blockers.
- Bulk-storing full-text research reports or copyrighted content before authorization is confirmed.

---

## 9. Acceptance Criteria

### 9.1 Minute-Level Data

| Item | Standard |
| --- | --- |
| Data coverage | Minute-level data for the MVP stock universe over the latest 1-2 years is fully ingested |
| Query performance | One stock's one-year 1-minute data can be returned within an acceptable time |
| Data quality | OHLC, nonnegative value, trading session, and minute-count completeness rules are online |
| Aggregation consistency | Minute-aggregated daily data matches daily source data within tolerance |
| Feature output | At least 10 first-batch intraday features can be generated stably |

### 9.2 Multi-Source Validation

| Item | Standard |
| --- | --- |
| Second source | At least one source other than Tushare is integrated |
| Validation scope | At least 3 of trading calendar, security master, daily market data, and adjustment factors are covered |
| Difference records | Differences can be traced to field, key, source values, and validation batch |
| Quality metrics | Coverage, discrepancy rate, latency, and abnormal rate can be calculated by source |
| Trusted view | At least one core data domain is provided downstream through a trusted view |

### 9.3 Information Agent

| Item | Standard |
| --- | --- |
| Source configuration | Sources can be enabled or disabled by category, with source level recorded |
| Collection loop | At least announcements, financial news, and characteristic data are integrated |
| Structured events | Event type, related stock, impact direction, confidence, and evidence can be produced |
| Report generation | Structured daily reports can be generated and persisted stably |
| Strategy linkage | Preliminary analysis can be performed on post-event price behavior and strategy holding exposure |

---

## 10. Resources and Dependencies

| Resource | Description |
| --- | --- |
| Data Engineering | Connector framework, ODS/DWD/DWS, scheduling, DQC, cross-source validation |
| Quant Research | Minute-level feature definitions, event impact labels, strategy linkage metrics, and acceptance criteria |
| Platform / Operations | ClickHouse storage, compute resources, backup, monitoring, and job SLA |
| Compliance / Procurement | Data authorization, API terms, copyright scope, and budget |
| AI / Application Engineering | Agent, LLM report generation, entity recognition, report service, and model version management |

Key dependencies:

- Authorization and trial access for a second data source.
- Authorization scope for historical minute-level data.
- Authorization and copyright boundaries for information sources.
- ClickHouse storage capacity and historical backfill window.
- Unified definitions for security master data, trading calendar, and PIT rules.

---

## 11. Recommended Near-Term Action List

| No. | Action | Suggested Owner | Output |
| ---: | --- | --- | --- |
| 1 | Confirm MVP stock universe, minute frequency, and historical time range | Quant Research + Data Engineering | MVP scope document |
| 2 | List second-source candidates and apply for trial/API documentation | Procurement/Compliance + Data Engineering | Data source evaluation table |
| 3 | Design `source_registry`, connector interfaces, and cross-source difference tables | Data Engineering | Technical design draft |
| 4 | Design minute-level DWD/DWS tables and first-batch features | Data Engineering + Quant Research | Table schema and feature list |
| 5 | Confirm Information Agent whitelist sources and copyright strategy | Compliance/Procurement + AI Engineering | Information source whitelist |
| 6 | Implement information daily report MVP: collection, structuring, reporting, persistence | AI Engineering + Data Engineering | Daily information report sample |
| 7 | Establish first-batch DQC and cross-source validation rules | Data Engineering | Quality rules and result tables |
| 8 | Prepare first management review package | Project Lead | Scope, cost, timeline, risks, and decision items |

---

## 12. Conclusion

The three workstreams solve different problems:

- Minute-level data solves the need to observe more granular market behavior, measure execution more accurately, and make backtesting more realistic.
- Multi-source validation solves whether data is trustworthy, whether errors can be detected, and whether production publication is stable.
- The Information Agent solves how major information can systematically enter research, reporting, and strategy impact analysis.

A phased implementation is recommended: first build minimum viable closed loops, then expand coverage. The most important near-term management decisions are to confirm the second-source trial and procurement path, confirm the historical minute-level data scope, and confirm the information source whitelist and authorization boundaries. Once these decisions are made, the technical implementation can be built progressively on the existing `tushare-integration + ClickHouse + DWD/DWS + DQC` foundation without replacing the current architecture.
