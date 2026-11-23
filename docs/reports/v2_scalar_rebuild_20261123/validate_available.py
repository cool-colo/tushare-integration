import json,time,sys
from pathlib import Path
import clickhouse_connect
from tushare_integration.dws import DWSManager
from tushare_integration.v2_scalar_extensions import SCALAR_SPECS
m=DWSManager();s=m.settings.database
c=clickhouse_connect.get_client(host=s.host,port=s.port,username=s.user,password=s.password,database=s.db_name,send_receive_timeout=900)
DB='v2_scalar_rebuild_20261123';ART=Path('docs/reports/v2_scalar_rebuild_20261123')
STAGE='available'
NEW=f'{DB}.dws_stock_factor_wide_v2_available_20261123';OLD=f'{s.db_name}.dws_stock_factor_wide_v2'
stock_filter=''
settings={'max_query_size':2097152,'max_ast_elements':500000,'max_threads':4,'max_memory_usage':17179869184,'max_execution_time':900}
def query(label,sql):
 label=label.replace('sample_',STAGE+'_');start=time.monotonic();r=list(c.query(sql,settings={**settings,'log_comment':'v2_scalar_rebuild_20261123:validate_'+label}).named_results())
 (ART/(label+'.json')).write_text(json.dumps(r,default=str,ensure_ascii=False,indent=2))
 print(label,'seconds',round(time.monotonic()-start,2),json.dumps(r[:25],default=str,ensure_ascii=False),flush=True)
 return r

query('sample_counts',f'SELECT count() AS rows,uniqExact(instrument_id,trade_date) AS unique_keys,min(trade_date) AS first,max(trade_date) AS last,uniqExact(source_code) AS stocks FROM {NEW}')
query('sample_counts_by_stock',f'SELECT source_code,count() AS rows,min(trade_date) AS first,max(trade_date) AS last FROM {NEW} GROUP BY source_code ORDER BY source_code')
query('sample_key_diff',f'''SELECT countIf(o.instrument_id='') AS only_new,countIf(n.instrument_id='') AS only_old FROM (SELECT instrument_id,trade_date FROM {OLD} WHERE {stock_filter}trade_date BETWEEN (SELECT min(trade_date) FROM {NEW}) AND (SELECT max(trade_date) FROM {NEW})) o FULL OUTER JOIN {NEW} n ON o.instrument_id=n.instrument_id AND o.trade_date=n.trade_date''')
cols=[r[0] for r in c.query('SELECT name FROM system.columns WHERE database={db:String} AND table={table:String}',parameters={'db':s.db_name,'table':'dws_stock_factor_wide_v2'}).result_rows]
ignored={'source','source_table','source_batch_id','source_record_hash','build_time'}
diffs=[]
names=[n for n in cols if n not in ignored]
for offset in range(0,len(names),128):
 checks=','.join(f"tuple('{n}',countIf(isNull(o.`{n}`) != isNull(n.`{n}`) OR ifNull(o.`{n}` != n.`{n}`,0)))" for n in names[offset:offset+128])
 diffs.extend(query(f'sample_old_value_diff_{offset:04d}',f'SELECT x.1 AS field,x.2 AS mismatches FROM (SELECT arrayJoin([{checks}]) AS x FROM (SELECT * FROM {OLD} WHERE {stock_filter}trade_date BETWEEN (SELECT min(trade_date) FROM {NEW}) AND (SELECT max(trade_date) FROM {NEW})) o INNER JOIN {NEW} n ON o.instrument_id=n.instrument_id AND o.trade_date=n.trade_date) WHERE x.2>0'))
(ART/(STAGE+'_old_value_diff.json')).write_text(json.dumps(diffs,ensure_ascii=False,indent=2))
checks=','.join(f"tuple('{item['name']}',countIf(`{item['name']}` IS NOT NULL))" for item in SCALAR_SPECS)
query('sample_new_coverage',f'SELECT x.1 AS field,x.2 AS non_null_rows FROM (SELECT arrayJoin([{checks}]) AS x FROM {NEW})')
checks=','.join(f"tuple('{item['name']}',countIf(NOT isFinite(`{item['name']}`)))" for item in SCALAR_SPECS if item['data_type']=='float')
query('sample_nonfinite',f'SELECT x.1 AS field,x.2 AS nonfinite_rows FROM (SELECT arrayJoin([{checks}]) AS x FROM {NEW}) WHERE x.2>0')
query('sample_proxies',f'''SELECT countIf(isNull(diluted_weighted_share_mrq_0)!=isNull(total_share_mrq_0) OR ifNull(diluted_weighted_share_mrq_0!=total_share_mrq_0,0) OR isNull(diluted_weighted_share_mrq_4)!=isNull(total_share_mrq_4) OR ifNull(diluted_weighted_share_mrq_4!=total_share_mrq_4,0)) AS proxy_mismatches,countIf(top_list_flag NOT IN (0,1) OR csi800_member NOT IN (0,1)) AS invalid_flags,countIf(analyst_forward_pe_12m<=0) AS nonpositive_pe FROM {NEW}''')
query('sample_days',f"SELECT trade_date,count() AS rows,uniqExact(source_code) AS stocks,countIf(endsWith(source_code,'.BJ')) AS beijing_rows FROM {NEW} GROUP BY trade_date ORDER BY trade_date") if STAGE=='available' else None
query('sample_price_keys',f"SELECT countIf(p.instrument_id='') AS candidate_only,countIf(n.instrument_id='') AS source_only FROM (SELECT instrument_id,event_date FROM {s.db_name}.dwd_stock_eod_price WHERE {stock_filter}event_date BETWEEN (SELECT min(trade_date) FROM {NEW}) AND (SELECT max(trade_date) FROM {NEW}) AND available_trade_date=toDate32('2026-11-23') AND sys_to=toDateTime64('9999-12-31 00:00:00',3)) p FULL OUTER JOIN {NEW} n ON p.instrument_id=n.instrument_id AND p.event_date=n.trade_date")
query('available_dates',f"SELECT countIf(trade_date!=toDate32('2026-11-20') OR available_trade_date!=toDate32('2026-11-23')) AS invalid_dates FROM {NEW}")
expected={col['name'] for col in m.load_spec('dws_stock_factor_wide_v2')['schema']['columns']}
actual={r[0] for r in c.query('SELECT name FROM system.columns WHERE database={db:String} AND table={table:String}',parameters={'db':DB,'table':'dws_stock_factor_wide_v2_available_20261123'}).result_rows}
schema={'expected_columns':len(expected),'actual_columns':len(actual),'missing':sorted(expected-actual),'unexpected':sorted(actual-expected)}
(ART/'available_schema.json').write_text(json.dumps(schema,indent=2));print('SCHEMA',schema,flush=True)
def read(name):return json.loads((ART/('available_'+name+'.json')).read_text())
coverage={r['field']:r['non_null_rows'] for r in read('new_coverage')}
placeholders=[p['name'] for p in SCALAR_SPECS if p['status']=='placeholder']
summary={'row_count':read('counts')[0]['rows'],'old_columns_compared':len(names),'old_field_mismatches':len(diffs),'implemented_fields':len(SCALAR_SPECS)-len(placeholders),'implemented_fields_with_values':sum(coverage[p['name']]>0 for p in SCALAR_SPECS if p['status']!='placeholder'),'implemented_fields_all_null':[p['name'] for p in SCALAR_SPECS if p['status']!='placeholder' and coverage[p['name']]==0],'placeholder_fields':len(placeholders),'placeholder_nonnull_rows':sum(coverage[n] for n in placeholders)}
(ART/'available_validation_summary.json').write_text(json.dumps(summary,indent=2));print('SUMMARY',json.dumps(summary),flush=True)
assert expected==actual and len(actual)==1968,schema
assert read('counts')[0]['rows']==read('counts')[0]['unique_keys']>0
assert all(v==0 for v in read('dates')[0].values()),read('dates')
assert all(v==0 for v in read('key_diff')[0].values()),read('key_diff')
assert all(v==0 for v in read('price_keys')[0].values()),read('price_keys')
assert all(v==0 for v in read('proxies')[0].values()),read('proxies')
assert not read('nonfinite'),read('nonfinite')
assert not diffs,diffs
assert summary['placeholder_nonnull_rows']==0
print('COMPLETE',flush=True)
