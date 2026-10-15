from ths_factor.api import FactorAPI
api = FactorAPI()

username = 'xxxxxxx'
password = 'xxxxxxx'

api.login(username, password)
print('finish login')

# api.set_env(sql_dst='sqlite:///D:/sdk/ths_factor/')
# print('finish set_env')

prod_list=api.get_product_list()
print(prod_list)

res=api.sync_data('2025-01-09','2025-01-15',['intraday_futures_oneminute'])
print(res)

# res = api.query('news_realtime_llmstandard','202512090900','202512091100')
# print(len(res))
#def on_push(prod_type, data):
#    print(prod_type, data)

#res=api.subscribe('news_realtime_llmstandard', on_push)
#print(res)
#input()

# res=api.unsubscribe('news_realtime_llmstandard')
# print(res)

res=api.read_data('select * from intraday_futures_oneminute limit 10')
print(res)

api.logout()
print('finish logout')