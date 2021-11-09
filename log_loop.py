import pymongo
import flask
from os import path
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
from flask_cors import *
import time
import pymongo.errors

# 连接mongodb
client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
# 作品信息集合
works = db.works
# 交易记录集合
record = db.record
# 已授权token集合
approve = db.approve
# 记录用户出售收益集合
sell = db.sell
# 记录用户分成收益集合
profit = db.profit
# 记录更新到的块
block = db.block

w3 = Web3(Web3.HTTPProvider('https://http-mainnet-node.huobichain.com'))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)
folder = 'works'
server = flask.Flask(__name__, static_url_path='/data', static_folder=folder)
CORS(server, supports_credetials=True)
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
tx_url = res['tx_url']
event_dict = {
    'price_set':
    '0xd765eb1cf8aab1a01381fef8dcc9f755ef2d2233849716da96a90e32da84821a',
    'auction_set':
    '0xd6eddd1118d71820909c1197aa966dbc15ed6f508554252169cc3d5ccac756ca',
    'transfer':
    '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef',
    'sale':
    '0xe8038e253f57f3f9c7277af1d801786319db71cc5491fe5db55a0e04f1b3466f',
    'bid':
    '0xcbf61548a249040d379a7f7a4486a18d78824bce978077f4943fb55e111af1c1',
    'control_token':
    '0xfc1e08f776282b1abf0734388c9042ad8206984bf5d69a721d120c9af38412fc'
}
block_num = block.count_documents({'_id':1})
if block_num == 0:
    block.insert_one({'_id':1,'block':w3.eth.get_block_number()})


# 生成交易字典
def make_dict(tx_hash, token_id, event_type, ad_from, ad_to, price, time_stamp,
              url):
    db_dict = {
        '_id': tx_hash,
        'token_id': token_id,
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
                works.update_one({'_id': token_id}, {'$set': {'flag': True}})
                approve.delete_one({'_id': token_id})
            else:
                ad_from = '0x' + topics[1].hex()[26:]
                ad_from = w3.toChecksumAddress(ad_from)
                if ad_to == black_address:
                    works.delete_one({'_id': token_id})
                    ad_to = ''
                    event_type = 'burn'
                else:
                    works.update_one(
                        {'_id': token_id}, 
                        {'$set': {
                            'owner': ad_to
                        }})
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
            try:
                for li in return_list:
                    if li['_id'] == tx_hash:
                        user_from = li['from']
                sell.insert_one({
                    '_id': tx_hash,
                    'token_id': token_id,
                    'user_address': user_from,
                    'price': str(int(buy_num * 0.85))
                })
            except Exception:
                pass
            sale_count = sell.count_documents({'token_id':token_id})
            if not sale_count == 1:
                try:
                    creator = contract.functions.uniqueTokenCreators(token_id,0).call()
                    profit.insert_one({
                        '_id': tx_hash,
                        'token_id': token_id,
                        'user_address': creator,
                        'price': str(int(buy_num * 0.1))
                    })
                except Exception:
                    pass
        elif topics[0].hex() == event_dict['auction_set']:
            token_id = int(data[:66], 16)
            time_begin = int(data[66:130], 16)
            time_end = int(data[130:], 16)
            state_gas = contract.functions.sellingState(token_id).estimateGas()
            res = contract.functions.sellingState(token_id).call(
                {'gas': state_gas})
            start_price = str(res[1])
            if start_price == '0':
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
                    'auction_start_time': time_begin,
                    'auction_end_time': time_end,
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
        elif topics[0].hex() == event_dict['control_token']:
            token_id = int(data[:66], 16)
            updated = int(data[706:], 16)
            works.update_one({'_id': token_id}, {'$set': {'stage': updated}})
    if not len(return_list) == 0:
        try:
            record.insert_many(return_list)
        except pymongo.errors.BulkWriteError:
            pass


# 事件循环
def log_loop():
    while 1:
        try:
            while 1:
                doc = block.find_one({'_id':1})
                fromBlock = doc['block']
                toBlock = w3.eth.block_number
                try:
                    event_list = w3.eth.getLogs({'address': address, 'fromBlock': fromBlock,'toBlock':toBlock})
                    if not len(event_list) == 0:
                        handle(event_list)
                except Exception as e:
                    print(e)
                fromBlock = toBlock+1
                block.update_one({'_id':1},{'$set':{'block':fromBlock}})
                time.sleep(3)
        except Exception as e:
            print(e)
        time.sleep(3)


log_loop()