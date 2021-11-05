import pymongo
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
import time
import pymongo.errors
from os import path


# 连接mongodb
client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
# 作品信息集合
works = db.works
# user信息集合
user = db.user
# 可用token_id集合
token_number = db.token
# 交易记录集合
record = db.record

w3 = Web3(Web3.HTTPProvider('https://http-mainnet-node.defibox.com'))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)
# 与合约交互
dir_path = path.dirname(path.realpath(__file__))
with open(str(path.join(dir_path, 'contract_abi.json')),
          'r') as abi_definition:
    abi = json.load(abi_definition)
with open('private.json', 'r') as f:
    res = json.load(f)
address = res['contract_address']
black_address = '0xe7a5B85218a9F685D89630e7312b5686cdD49175'
contract = w3.eth.contract(address=address, abi=abi)
tx_url = 'https://hecoinfo.com/tx/'
event_dict = {
    'price_set':
    '0xd765eb1cf8aab1a01381fef8dcc9f755ef2d2233849716da96a90e32da84821a',
    'auction_set':
    '0xd6eddd1118d71820909c1197aa966dbc15ed6f508554252169cc3d5ccac756ca',
    'transfer':
    '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
    'sale':
    '0xe8038e253f57f3f9c7277af1d801786319db71cc5491fe5db55a0e04f1b3466f',
    'bid': '0xcbf61548a249040d379a7f7a4486a18d78824bce978077f4943fb55e111af1c1'
}


# 生成交易字典
def make_dict(tx_hash, token_id, event_type, ad_from, ad_to, price, time_stamp, url):
    db_dict = {
        '_id': tx_hash,
        'token_id':token_id,
        'type': event_type,
        'from': ad_from,
        'to': ad_to,
        'price': price,
        'time': time_stamp,
        'url': url
    }
    return db_dict


# 处理事件
def handle(event_list):
    return_list = []
    for event in event_list:
        topics = event['topics']
        data = event['data']
        tx_hash = event['transactionHash'].hex()
        url = tx_url + tx_hash
        block_num = event['blockNumber']
        block_data = w3.eth.get_block(block_num)
        time_stamp = block_data['timestamp']
        if topics[0].hex() == event_dict['transfer']:
            ad_to = '0x' + topics[2].hex()[26:]
            ad_to = w3.toChecksumAddress(ad_to)
            token_id = int(topics[3].hex(), 16)
            if int(topics[1].hex()[2:], 16) == 0:
                ad_from = ''
                event_type = 'mint'
            else:
                ad_from = '0x' + topics[1].hex()[26:]
                ad_from = w3.toChecksumAddress(ad_from)
                if ad_to == black_address:
                    works.delete_one({'_id': token_id})
                    ad_to = ''
                    event_type = 'burn'
                else:
                    event_type = 'transfer'
            tx_dict = make_dict(tx_hash, token_id, event_type, ad_from, ad_to,
                                '0', time_stamp, url)
            return_list.append(tx_dict)
        elif topics[0].hex() == event_dict['bid']:
            token_id = int(data[:66], 16)
            bid_num = int(data[66:130], 16)
            user_address = w3.toChecksumAddress('0x' + data[154:])
            tx_dict = make_dict(tx_hash, token_id, 'bid', user_address, '',
                                str(bid_num), time_stamp, url)
            return_list.append(tx_dict)
        elif topics[0].hex() == event_dict['sale']:
            token_id = int(data[:66], 16)
            buy_num = int(data[66:130], 16)
            user_address = w3.toChecksumAddress('0x' + data[154:])
            for li in return_list:
                if li['_id'] == tx_hash:
                    li['type'] = 'sale'
                    li['price'] = str(buy_num)
        elif topics[0].hex() == event_dict['auction_set']:
            token_id = int(data[:66], 16)
            time_begin = int(data[66:130], 16)
            time_end = int(data[130:], 16)
            state_gas = contract.functions.sellingState(token_id).estimateGas()
            res = contract.functions.sellingState(token_id).call(
                {'gas': state_gas})
            start_price = str(res[1])
            if start_price == 0:
                state2 = 0
            else:
                now_time = time.time()
                if now_time < time_begin:
                    state2 = 1
                elif now_time > time_end:
                    state2 = 3
                else:
                    state2 = 2
            works.update_one(
                {'_id': token_id},
                {'$set': {
                    'start_price': start_price,
                    'state2': state2
                }})
        elif topics[0].hex() == event_dict['price_set']:
            token_id = int(data[:66], 16)
            buy_price = int(data[66:], 16)
            if buy_price == 0:
                works.update_one({'_id': token_id}, {'$set': {'state1': 0}})
            else:
                works.update_one(
                    {'_id': token_id},
                    {'$set': {
                        'state1': 1,
                        'buy_price': str(buy_price)
                    }})
    if not len(return_list) == 0:
        try:
            record.insert_many(return_list)
        except pymongo.errors.BulkWriteError:
            pass


# 事件循环
def log_loop():
    begin = 8126082
    print(w3.eth.get_block_number())
    while begin < w3.eth.get_block_number():
        try:
            li = w3.eth.getLogs({'address':address, 'fromBlock':begin,'toBlock':begin+5000})
            if not len(li) == 0:
                handle(li)
            begin = begin + 5000
        except ValueError as e:
            print(e)


log_loop()
cursor = works.find({'type':'layer'})
for doc in cursor:
    a = contract.functions.getControlToken(doc['_id']).call()
    works.update_one({'_id':doc['_id']},{'$set':{'stage':a[2]}})

works.update_many({},{'$set':{'collector':[]}})
user.update_many({},{'$set':{'follows':[],'fans':[]}})