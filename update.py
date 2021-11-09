import pymongo
from os import path
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
import time
import pymongo.errors
import asyncio


# 连接mongodb
client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
# 作品信息集合
works = db.works

w3 = Web3(Web3.HTTPProvider('https://http-mainnet-node.huobichain.com'))
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


# 判断token是否在链上
def judge(token_id):
    try:
        contract.functions.tokenURI(token_id).estimateGas()
        return True
    except Exception as e:
        return False


# 数据库更新
async def up(doc):
    token_id = doc['_id']
    try:
        owner_gas = contract.functions.ownerOf(token_id).estimateGas()
        owner = contract.functions.ownerOf(token_id).call({'gas': owner_gas})
        if owner == black_address:
            works.delete_one({'_id': token_id})
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
                canvas_doc = works.find_one({'_id': canvas_token_id})
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
        works.update_one({'_id': token_id}, {
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
        cursor = works.find()
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        loop = asyncio.get_event_loop()
        tasks = [up(doc) for doc in cursor]
        loop.run_until_complete(asyncio.wait(tasks))
        time.sleep(60)


update()