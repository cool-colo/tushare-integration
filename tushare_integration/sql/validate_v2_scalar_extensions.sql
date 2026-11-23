-- Read-only acceptance queries. Build candidate tables before running these.
-- Compare all 1,736 non-audit old columns with the generator documented in
-- docs/v2_scalar_extensions_rebuild.md. No CREATE/ALTER/EXCHANGE in this file.

SELECT count() AS rows, uniqExact(instrument_id, trade_date) AS keys,
       min(trade_date), max(trade_date)
FROM default.dws_stock_factor_wide_v2_candidate;

-- These 13 columns deliberately have no supported input contract yet.
SELECT countIf(share_action_factor IS NOT NULL
    OR fund_report_hold_shares_total IS NOT NULL OR fund_report_holder_count IS NOT NULL
    OR national_team_hold_shares IS NOT NULL OR national_team_free_hold_shares IS NOT NULL
    OR national_team_hold_shares_prev_report IS NOT NULL OR national_team_report_close IS NOT NULL
    OR national_team_report_close_prev_report IS NOT NULL OR national_team_report_free_float_mv IS NOT NULL
    OR national_team_hold_free_share_ratio IS NOT NULL OR national_team_hold_free_share_ratio_prev_report IS NOT NULL
    OR company_province IS NOT NULL OR company_city IS NOT NULL) AS unexpected_placeholder_values
FROM default.dws_stock_factor_wide_v2_candidate;

-- Both quantities are in shares; the diluted value is an explicitly agreed proxy.
SELECT countIf(isNull(diluted_weighted_share_mrq_0) != isNull(total_share_mrq_0)
            OR ifNull(diluted_weighted_share_mrq_0 != total_share_mrq_0, 0)
            OR isNull(diluted_weighted_share_mrq_4) != isNull(total_share_mrq_4)
            OR ifNull(diluted_weighted_share_mrq_4 != total_share_mrq_4, 0)) AS proxy_mismatches,
       countIf(top_list_flag NOT IN (0,1) OR csi800_member NOT IN (0,1)) AS invalid_flags,
       countIf(analyst_forward_pe_12m <= 0) AS nonpositive_forward_pe
FROM default.dws_stock_factor_wide_v2_candidate;

-- Verify conservative next-open-day availability in the new DWD layers.
SELECT 'holders' AS source, countIf(available_trade_date <= ann_date) AS invalid_visibility
FROM default.dwd_stock_holder_number
UNION ALL
SELECT 'top_list', countIf(available_trade_date <= event_date)
FROM default.dwd_stock_top_list;

-- Individual source/report boundary samples: inspect before, on, and after
-- report availability. _mrq_0 is fixed to this expected period, even if absent.
SELECT source_code, trade_date, available_trade_date,
       addDays(toStartOfQuarter(addDays(available_trade_date,1)),-1) AS mrq_0_period,
       revenue_mrq_0, revenue_mrq_1, revenue_ttm_12,
       rd_exp_lyr_0, rd_exp_indicator_lyr_0, holder_num_mrq_0, holder_num_mrq_1,
       basic_eps_lyr_10, analyst_np_consensus_fy0, analyst_np_consensus_fy1
FROM default.dws_stock_factor_wide_v2_candidate
WHERE source_code='000001.SZ' AND trade_date BETWEEN '2026-04-01' AND '2026-05-15'
ORDER BY trade_date;
