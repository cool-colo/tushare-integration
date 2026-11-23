import argparse
import bisect
import json
from pathlib import Path
import clickhouse_connect
from tushare_integration.dwd import DWDManager
from tushare_integration.quality import QualityManager
p=argparse.ArgumentParser();p.add_argument('--reuse-quality',action='store_true');p.add_argument('tables',nargs='+');args=p.parse_args()
m=DWDManager();s=m.settings.database;source=s.db_name
c=clickhouse_connect.get_client(host=s.host,port=s.port,username=s.user,password=s.password,database=source,send_receive_timeout=900)
db='v2_array_dwd_rebuild_20261123';m.settings.database.db_name=db
settings={'max_threads':2,'max_memory_usage':17179869184,'max_bytes_before_external_group_by':1073741824,'max_bytes_before_external_sort':1073741824,'max_execution_time':600}
art=Path('docs/reports/v2_array_dwd_20261123')
opens=[r[0] for r in c.query(f"SELECT DISTINCT cal_date FROM {source}.trade_cal WHERE exchange='SSE' AND is_open=1 ORDER BY cal_date").result_rows]
def query(sql):return list(c.query(sql,settings=settings).named_results())
for table in args.tables:
 spec=m.load_spec(table);qt=table+'_quarantine';result={}
 result['normal']=query(f'SELECT count() AS rows,uniqExact(instrument_id) AS instruments,min(event_date) AS first_event,max(event_date) AS last_event,min(available_trade_date) AS first_available,max(available_trade_date) AS last_available,countIf(available_trade_date IS NULL) AS unknown_availability FROM {db}.{table}')[0]
 key=spec.get('business_key') or m.load_source_schema(spec['source']['schema_name'])['primary_key']
 keys=','.join('`'+k+'`' for k in key)
 result['quarantine']=query(f'SELECT count() AS rows,uniqExact(tuple({keys})) AS business_keys,countIf(available_trade_date IS NOT NULL OR sys_to IS NOT NULL) AS improperly_visible FROM {db}.{qt}')[0]
 assert result['quarantine']['improperly_visible']==0
 join=' AND '.join(f'isNotDistinctFrom(n.`{k}`,q.`{k}`)' for k in key)
 result['normal_quarantine_key_overlap']=query(f'SELECT count() AS overlaps FROM {db}.{table} n INNER JOIN (SELECT DISTINCT {keys} FROM {db}.{qt}) q ON {join}')[0]['overlaps']
 assert result['normal_quarantine_key_overlap']==0
 if spec.get('availability_mode')=='unknown_disclosure':
  assert result['normal']['rows']==result['normal']['unknown_availability']
  result['calendar_check']={'eligible_for_public_date_pit':False,'reason':'unknown_disclosure_date'}
 else:
  base="greatest(report_date,toDate(create_time))" if table=='dwd_stock_research_report' else 'ann_date'
  groups=query(f'SELECT {base} AS base_date,available_trade_date,count() AS rows FROM {db}.{table} GROUP BY base_date,available_trade_date')
  invalid=[]
  for r in groups:
   idx=bisect.bisect_right(opens,r['base_date'])
   expected=opens[idx] if idx<len(opens) else None
   if r['available_trade_date']!=expected:invalid.append({**r,'expected':expected})
  result['calendar_check']={'groups_checked':len(groups),'rows_checked':sum(r['rows'] for r in groups),'invalid':invalid}
  assert not invalid
 checks=[]
 if args.reuse_quality:
  checks=[{'rule':r['rule'],'severity':r['severity'],'issues':r['result'][0]['issue_count']} for r in json.loads((art/(table+'_quality.json')).read_text())]
 else:
  for rule in QualityManager(settings=m.settings).build_rules('dwd',table,table):
   rows=query(rule.issue_count_sql);checks.append({'rule':rule.rule_id,'severity':rule.severity,'issues':rows[0]['issue_count']})
 result['quality']=checks
 (art/(table+'_final_audit.json')).write_text(json.dumps(result,default=str,indent=2))
 print(table,json.dumps(result,default=str),flush=True)
 assert not [r for r in checks if r['severity']=='BLOCKER' and r['issues']>0]
print('COMPLETE',flush=True)
