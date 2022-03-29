import pymongo
import flask
from os import path
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
from flask_cors import *
import time
import pymongo.errors
from threading import Thread
import asyncio
import os

# 连接mongodb
client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
# 作品信息集合
works = db.works
# 记录更新到的块
block = db.block
# 可用token_id集合
token_number = db.token

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
address = res['multiple_contract']
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
while 1:
    try:
        number = contract.functions.expectedTokenSupply().call()
        print('success')
        break
    except Exception:
        time.sleep(1)
        pass
if token_number.count() == 0:
    token_number.insert_one({'_id': 1, 'token_num': number})
else:
    token_number.update_one({'_id': 1}, {'$set': {'token_num': number}})
if not os.path.exists(folder):
    os.mkdir(folder)
if not os.path.exists('{}/avatar'.format(folder)):
    os.mkdir('{}/avatar'.format(folder))
if not os.path.exists('{}/small'.format(folder)):
    os.mkdir('{}/small'.format(folder))


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
                works.update_one({'token_id': token_id,'contract':'v1'}, {'$set': {'flag': True}})
            else:
                ad_from = '0x' + topics[1].hex()[26:]
                ad_from = w3.toChecksumAddress(ad_from)
                if ad_to == black_address:
                    works.delete_one({'token_id': token_id,'contract':'v1'})
                    ad_to = ''
                    event_type = 'burn'
                else:
                    works.update_one(
                        {'token_id':token_id,'contract':'v1'},
                        {'$set': {
                            'owner': ad_to
                        }})
                    event_type = 'transfer'
            tx_dict = make_dict(tx_hash, token_id, event_type, ad_from, ad_to,
                                '0', time_stamp, url)
            return_list.append(tx_dict)
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
                {'token_id': token_id, 'contract':'v1'},
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
                works.update_one({
                    'token_id': token_id,
                    'contract': 'v1'
                }, {'$set': {
                    'state1': 0
                }})
            else:
                works.update_one(
                    {'token_id': token_id, 'contract':'v1'},
                    {'$set': {
                        'state1': 1,
                        'buy_price': str(buy_price)
                    }})


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
                    pass
                fromBlock = toBlock+1
                block.update_one({'_id':1},{'$set':{'block':fromBlock}})
                time.sleep(3)
        except Exception as e:
            pass
        time.sleep(3)


# 判断token是否在链上
def judge(token_id):
    try:
        contract.functions.tokenURI(token_id).estimateGas()
        return True
    except Exception as e:
        return False


# 数据库更新
async def up(doc):
    token_id = doc['token_id']
    try:
        owner_gas = contract.functions.ownerOf(token_id).estimateGas()
        owner = contract.functions.ownerOf(token_id).call({'gas': owner_gas})
        if owner == black_address:
            works.delete_one({'token_id': token_id})
            return
        if judge(token_id):
            if doc['type'] == 'single':
                flag = True
            elif doc['type'] == 'canvas':
                layer_token = doc['data']
                flag = True
                for i in layer_token:
                    flag = flag and judge(i)
            else:
                layer_json = doc['json_data']
                layer_json = json.loads(layer_json)
                canvas_token_id = layer_json['canvas_token_id']
                canvas_doc = works.find_one({'token_id': canvas_token_id})
                flag = canvas_doc['flag']
        else:
            flag = False
        state_gas = contract.functions.sellingState(token_id).estimateGas()
        res = contract.functions.sellingState(token_id).call(
            {'gas': state_gas})
        buy_price = str(res[0])
        start_price = str(res[1])
        max_price = '0'
        end_price = '0'
        auction_start_time = res[2]
        auction_end_time = res[3]
        if res[0] == 0:
            state1 = 0
        else:
            state1 = 1
        if res[1] == 0:
            state2 = 0
        else:
            t = time.time()
            now_time = int(t)
            if now_time < res[2]:
                state2 = 1
            elif not now_time < res[2] and not now_time > res[3]:
                state2 = 2
                pending_gas = contract.functions.pendingBids(
                    token_id).estimateGas()
                pending = contract.functions.pendingBids(token_id).call(
                    {'gas': pending_gas})
                max_price = str(pending[1])
            else:
                state2 = 3
                pending_gas = contract.functions.pendingBids(
                    token_id).estimateGas()
                pending = contract.functions.pendingBids(token_id).call(
                    {'gas': pending_gas})
                end_price = str(pending[1])
        works.update_one({'token_id': token_id, 'contract':'v1'}, {
            '$set': {
                'owner': owner,
                'state1': state1,
                'state2': state2,
                'auction_start_time': auction_start_time,
                'auction_end_time': auction_end_time,
                'buy_price': buy_price,
                'start_price': start_price,
                'max_price': max_price,
                'end_price': end_price,
                'flag': flag,
            }
        })
    except Exception as e:
        pass


# 更新数据库内容
def update():
    while 1:
        try:
            cursor = works.find({'contract':'v1'})
            new_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(new_loop)
            loop = asyncio.get_event_loop()
            tasks = [up(doc) for doc in cursor]
            loop.run_until_complete(asyncio.wait(tasks))
            time.sleep(60)
        except Exception:
            pass


t1 = Thread(target=log_loop)
t1.start()
t2 = Thread(target=update)
t2.start()