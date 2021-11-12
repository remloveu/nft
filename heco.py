import pymongo
import os
import base64
import imageio
from shutil import copyfile
import moviepy.editor as mp
from PIL import Image
from werkzeug.utils import secure_filename
import flask
from flask import request, jsonify
from os import path
from web3 import Web3
from web3.middleware import geth_poa_middleware
import json
import requests
from flask_cors import *
import time
from queue import Queue
import pymongo.errors
from threading import Thread
import web3.exceptions
import asyncio

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
q = Queue()
p = Queue()
number = contract.functions.expectedTokenSupply().call()
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
wallet_address = res['wallet_address']
private_key = res['private_key']
endpoint = 'https://api.pinata.cloud/'
host = res['host']
url = host + 'data/'
small_url = url + 'small/'
headers = {
    'pinata_api_key': res['pinata_api_key'],
    'pinata_secret_api_key': res['pinata_secret_api_key'],
}
tx_url = res['tx_url']
pinata_url = res['pinata_url']
web_url = res['web_url']
record.create_index([('time', -1)])
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


# 生成metadata
def make_json(name,
              data_type,
              creator,
              create_time,
              introduce,
              token_id,
              canvas_token_id,
              data_hash,
              tags,
              file_type,
              width=0,
              height=0):
    if data_type == 'canvas':
        image = ''
    elif data_type == 'layer':
        image = []
        for k in data_hash:
            image.append(pinata_url + k)
    else:
        image = pinata_url + data_hash[0]
    parameters = {
        'name': name,
        'type': data_type,
        'creator': creator,
        'create_time': create_time,
        'description': introduce,
        'token_id': token_id,
        'canvas_token_id': canvas_token_id,
        'hash': data_hash,
        'tags': tags,
        'file_type': file_type,
        'width': width,
        'height': height,
        'image': image,
        'external_url': web_url + str(token_id),
        'animation_url': '',
    }
    json_str = json.dumps(parameters)
    return json_str


# 根据字符串获取hash
def get_hash(string, flag):
    if flag:
        f = open(string, 'rb')
        files = {'file': f}
    else:
        files = {'file': string}
    response = requests.post('http://127.0.0.1:5001/api/v0/add', files=files)
    if flag:
        f.close()
    data = json.loads(response.text)
    hash_code = data['Hash']
    return hash_code


# 将字符串添加到pinata
def pin_file_to_ipfs():
    while 1:
        if not q.empty():
            file_path = q.get()
            url = endpoint + 'pinning/pinFileToIPFS'
            f = open(file_path, 'rb')
            files = {'file': f}
            requests.post(url, files=files, headers=headers)
            f.close()
        time.sleep(3)


def pin_str_to_ipfs():
    while 1:
        if not p.empty():
            meta_str = p.get()
            url = endpoint + 'pinning/pinFileToIPFS'
            files = {'file': meta_str}
            requests.post(url, files=files, headers=headers)
        time.sleep(3)


# 根据地址获取具体信息
def info(user_address, param):
    doc = user.find_one({'_id': user_address})
    if doc['avatar']:
        doc['avatar'] = url + doc['avatar']
    return doc[param]


# 根据地址获取作品
def get_works_from_user(pos, user_address, user_type, page, pic, state):
    limit = 9
    if not pic:
        cursor_dict = {}
    else:
        cursor_dict = {'type': pic}
    if state:
        if state == 'purchase':
            cursor_dict['state1'] = 1
        elif state == 'auction':
            cursor_dict['state2'] = 2
        elif state == 'auctioned':
            cursor_dict['state2'] = 1
        else:
            cursor_dict['state1'] = 0
            cursor_dict['state2'] = 0
    if pos == 1:
        cursor_dict[user_type] = user_address
    if pos == 2:
        cursor_dict[user_type] = {'$elemMatch': {'$eq': user_address}}
    cursor_dict['flag'] = True
    cursor = works.find(cursor_dict).sort([('_id', 1)])
    data_count = works.find(cursor_dict).count()
    if data_count % limit == 0:
        total_page = int(data_count / limit)
    else:
        total_page = int(data_count / limit) + 1
    start = (page - 1) * limit
    if page == total_page:
        end = data_count
    else:
        end = start + limit
    index = 0
    return_list = []
    for doc in cursor:
        if not index < end:
            break
        if not index < start:
            try:
                json_dict = {
                    'token_id': doc['_id'],
                    'name': doc['name'],
                    'type': doc['type'],
                    'creator_address': doc['creator'],
                    'creator_avatar': info(doc['creator'], 'avatar'),
                    'owner_address': doc['owner'],
                    'owner_avatar': info(doc['owner'], 'avatar'),
                    'state1': doc['state1'],
                    'state2': doc['state2'],
                }
                if json_dict['state1'] == 1:
                    json_dict['buy_price'] = int(doc['buy_price'])
                if not json_dict['state2'] == 0:
                    json_dict['auction_start_time'] = doc['auction_start_time']
                    json_dict['auction_end_time'] = doc['auction_end_time']
                    json_dict['start_price'] = int(doc['start_price'])
                    if json_dict['state2'] == 2:
                        json_dict['max_price'] = int(doc['max_price'])
                    if json_dict['state2'] == 3:
                        json_dict['end_price'] = int(doc['end_price'])
                if doc['type'] == 'canvas':
                    arr = []
                    data = doc['data']
                    for i in data:
                        layer_doc = works.find_one({'_id': i})
                        data = layer_doc['data']
                        for j in range(len(data)):
                            data[j] = small_url + data[j]
                        arr.append(data)
                    json_dict['layers'] = arr
                elif doc['type'] == 'layer':
                    layer_arr = doc['data']
                    for i in range(len(layer_arr)):
                        layer_arr[i] = small_url + layer_arr[i]
                    json_dict['layer'] = layer_arr
                    json_dict['stage'] = doc['stage']
                else:
                    if doc['is_movie']:
                        single_data = doc['data'].rsplit('.')[0] + '.mp4'
                        json_dict['single'] = small_url + single_data
                    else:
                        json_dict['single'] = small_url + doc['data']
                return_list.append(json_dict)
            except Exception as e:
                server.logger.exception('token_id:{} {}'.format(doc['_id'], e))
        index = index + 1
    return json.dumps(
        dict(count=data_count,
             total_page=total_page,
             page=page,
             data=return_list))


# 添加新用户到数据库
def add_user(user_address):
    t = time.time()
    user.insert_one({
        '_id': user_address,
        'area': '',
        'avatar': '',
        'email': '',
        'introduce': '',
        'name': '',
        'ts': int(t),
        'web': '',
        'follows': [],
        'fans': [],
    })


# 插入作品到数据库
def add_works(token_id,
              data,
              metadata_hash,
              user_address,
              introduce,
              create_time,
              name,
              json_data,
              work_type,
              is_movie=False,
              width=0,
              height=0):
    works.insert_one({
        '_id': token_id,
        'data': data,
        'is_movie': is_movie,
        'metadata_hash': metadata_hash,
        'owner': user_address,
        'creator': user_address,
        'collector': [],
        'introduce': introduce,
        'create_time': create_time,
        'name': name,
        'json_data': json_data,
        'type': work_type,
        'width': width,
        'height': height,
        'flag': False,
        'state1': 0,
        'state2': 0,
        'auction_start_time': 0,
        'auction_end_time': 0,
        'buy_price': '0',
        'start_price': '0',
        'max_price': '0',
        'end_price': '0',
        'stage': 0,
    })


# 授权token_id
def approve_token(user_address, main_token, second_num):
    nonce = w3.eth.get_transaction_count(wallet_address, 'pending')
    transact = {'gas': 160000, 'nonce': nonce}
    transaction = contract.functions.whitelistTokenForCreator(
        user_address, main_token, second_num, 15, 5).buildTransaction(transact)
    tx = w3.eth.account.sign_transaction(transaction, private_key)
    tx_hash = w3.eth.send_raw_transaction(tx.rawTransaction)
    tx_hash = tx_hash.hex()
    w3.eth.wait_for_transaction_receipt(tx_hash)


# small_size
def small_size(w, h, x=379, y=350):
    while w > x and h > y:
        w = int(w * 0.9)
        h = int(h * 0.9)
    return w, h


# 压缩
def compress(old_path, new_path):
    file_type = old_path.rsplit('.')[-1].lower()
    if file_type in ['mp4', 'm4v', 'mov']:
        reader = imageio.get_reader(old_path)
        pix_fmt = reader.get_meta_data()['pix_fmt']
        if pix_fmt == 'yuvj420p(pc':
            temp_path = old_path.rsplit('.')[0] + '_temp.' + file_type
            os.system('ffmpeg -i {} -pix_fmt yuv420p {}'.format(
                old_path, temp_path))
        else:
            temp_path = old_path
        clip = mp.VideoFileClip(temp_path)
        w_frame, h_frame = clip.w, clip.h
        w, h = small_size(w_frame, h_frame)
        clip_resized = clip.resize(height=h)
        clip_resized.write_videofile(new_path)
        if pix_fmt == 'yuvj420p(pc':
            os.remove(temp_path)
    elif file_type == 'gif':
        clip = mp.VideoFileClip(old_path)
        clip.write_videofile(new_path)
    else:
        im = Image.open(old_path)
        if os.path.getsize(old_path) < 500 * 1024:
            copyfile(old_path, new_path)
        else:
            w_frame, h_frame = im.size
            w, h = small_size(w_frame, h_frame)
            im.thumbnail((w, h))
            if file_type == 'jpeg' or file_type == 'jpg':
                im = im.convert('RGB')
            im.save(new_path, transparent=True)


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
            works.update_one({'_id': token_id},
                             {'$set': {
                                 'state1': 0,
                                 'state2': 0
                             }})
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
                    pass
                fromBlock = toBlock+1
                block.update_one({'_id':1},{'$set':{'block':fromBlock}})
                time.sleep(3)
        except Exception as e:
            pass
        time.sleep(3)


# 获取token_id
@server.route('/get_token', methods=['POST'])
def get_token():
    # 获取当前token_id
    lock = request.environ['HTTP_FLASK_LOCK']
    data = request.form.get('address')
    data = json.loads(data)
    user_address = Web3.toChecksumAddress(data['user_address'])
    if not contract.functions.artistWhitelist(user_address).call(
        {'gas': 50000}):
        return {}
    width = data['width']
    height = data['height']
    create_time = data['create_time']
    canvas = request.form.get('canvas')
    canvas = json.loads(canvas)
    layer = request.form.get('layer')
    layer = json.loads(layer)
    lock.acquire()
    doc = token_number.find_one({'_id': 1})
    token_num = doc['token_num']
    token_number.update_one(
        {'_id': 1}, {'$set': {
            'token_num': token_num + len(layer) + 1
        }})
    token_id = token_num
    approve_token(user_address, token_id, len(layer))
    lock.release()
    if not os.path.exists(folder + '/' + user_address):
        os.mkdir(folder + '/' + user_address)
    if not os.path.exists(folder + '/small/' + user_address):
        os.mkdir(folder + '/small/' + user_address)
    files = request.files
    index = 0
    layer_token = []
    return_list = []
    for i in layer:
        layer_arr = []
        layer_token_id = token_id + index + 1
        layer_token.append(layer_token_id)
        path_arr = []
        for num in range(i['count']):
            t = time.time()
            file_str = 'str_' + str(index) + '_' + str(num)
            file_name = secure_filename(files[file_str].filename)
            img = file_name.rsplit('.')[-1].lower()
            img_path = '{}/{}/{}.{}'.format(folder, user_address, str(int(t)),
                                            img)
            files[file_str].save(img_path)
            layer_hash = get_hash(img_path, True)
            new_name = str(layer_token_id) + '_' + layer_hash + '.' + img
            new_path = '{}/{}/{}'.format(folder, user_address, new_name)
            small_path = '{}/small/{}/{}'.format(folder, user_address,
                                                 new_name)
            os.rename(img_path, new_path)
            compress(new_path, small_path)
            q.put(new_path)
            path_arr.append(new_path[6:])
            layer_arr.append(layer_hash)
        doc = layer[index]
        layer_json = make_json(doc['name'], 'layer', user_address, create_time,
                               doc['introduce'], layer_token_id, token_id,
                               layer_arr, [], 'png', width, height)
        p.put(layer_json)
        layer_metadata_hash = get_hash(layer_json, False)
        # layer_num = works.count_documents({'_id': layer_token_id})
        # if layer_num == 1:
        #     works.delete_one({'_id': layer_token_id})
        try:
            add_works(layer_token_id, path_arr, layer_metadata_hash,
                      user_address, doc['introduce'], create_time, doc['name'],
                      layer_json, 'layer', False, width, height)
        except Exception as e:
            server.logger.exception(e)
        json_dict = {
            'type': 'layer',
            'token_id': layer_token_id,
            'layer_metadata_hash': pinata_url + layer_metadata_hash,
        }
        return_list.append(json_dict)
        approve.insert_one({
            '_id': layer_token_id,
            'type': 'layer',
            'user_address': user_address,
            'hash': layer_metadata_hash,
        })
        index = index + 1
    canvas_json = make_json(canvas['name'], 'canvas', user_address,
                            create_time, canvas['introduce'], token_id,
                            token_id, layer_token, [], '', width, height)
    p.put(canvas_json)
    canvas_metadata_hash = get_hash(canvas_json, False)
    canvas_dict = {
        'type': 'canvas',
        'token_id': token_id,
        'canvas_metadata_hash': pinata_url + canvas_metadata_hash,
    }
    return_list.append(canvas_dict)
    approve.insert_one({
        '_id': token_id,
        'type': 'canvas',
        'user_address': user_address,
        'hash': canvas_metadata_hash,
    })
    # canvas_num = works.count_documents({'_id': token_id})
    # if canvas_num == 1:
    #     works.delete_one({'_id': token_id})
    try:
        add_works(token_id, layer_token, canvas_metadata_hash, user_address,
                  canvas['introduce'], create_time, canvas['name'],
                  canvas_json, 'canvas', False, width, height)
    except Exception as e:
        server.logger.exception(e)
    return jsonify(return_list)


# 获取单一铸币的token
@server.route('/single_token', methods=['POST'])
def single_token():
    # 获取当前token_id
    lock = request.environ['HTTP_FLASK_LOCK']
    user_address = request.form.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    if not contract.functions.artistWhitelist(user_address).call(
        {'gas': 50000}):
        return {}
    name = request.form.get('name')
    introduce = request.form.get('introduce')
    create_time = request.form.get('create_time')
    create_time = int(create_time)
    lock.acquire()
    doc = token_number.find_one({'_id': 1})
    token_num = doc['token_num']
    token_number.update_one({'_id': 1}, {'$set': {'token_num': token_num + 1}})
    token_id = token_num
    approve_token(user_address, token_id, 0)
    lock.release()
    if not os.path.exists(folder + '/' + user_address):
        os.mkdir(folder + '/' + user_address)
    if not os.path.exists(folder + '/small/' + user_address):
        os.mkdir(folder + '/small/' + user_address)
    single_file = request.files['str']
    file_name = secure_filename(single_file.filename)
    img = file_name.rsplit('.')[-1].lower()
    if img in ['mp4', 'm4v', 'mov', 'gif']:
        is_movie = True
    else:
        is_movie = False
    t = time.time()
    img_path = '{}/{}/{}.{}'.format(folder, user_address, str(int(t)), img)
    single_file.save(img_path)
    single_hash = get_hash(img_path, True)
    new_name = str(token_id) + '_' + single_hash + '.' + img
    new_path = '{}/{}/{}'.format(folder, user_address, new_name)
    small_path = '{}/small/{}/{}'.format(folder, user_address, new_name)
    if is_movie:
        small_path = small_path.rsplit('.')[0] + '.mp4'
    os.rename(img_path, new_path)
    compress(new_path, small_path)
    q.put(new_path)
    single_json = make_json(name, 'single', user_address, create_time,
                            introduce, token_id, token_id, [single_hash], [],
                            img)
    p.put(single_json)
    single_metadata_hash = get_hash(single_json, False)
    user_number = user.count_documents({'_id': user_address})
    if user_number == 0:
        add_user(user_address)
    # single_num = works.count_documents({'_id': token_id})
    # if single_num == 1:
    #     works.delete_one({'_id': token_id})
    try:
        add_works(token_id, new_path[6:], single_metadata_hash, user_address,
                  introduce, create_time, name, single_json, 'single',
                  is_movie)
    except Exception as e:
        server.logger.exception(e)
    json_dict = {
        'token_id': token_id,
        'single_metadata_hash': pinata_url + single_metadata_hash,
    }
    approve.insert_one({
            '_id': token_id,
            'user_address': user_address,
            'type': 'single',
            'hash': single_metadata_hash,
        })
    return json_dict


# 画廊图片展示
@server.route('/show_pic', methods=['GET'])
def show_pic():
    page = request.args.get('page')
    state = request.args.get('state')
    pic = request.args.get('pic')
    page = int(page)
    result = get_works_from_user(0, '', '', int(page), pic, state)
    return result


# 根据用户地址获取资产
@server.route('/get_pic', methods=['GET'])
def get_pic():
    user_address = request.args.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    page = request.args.get('page')
    state = request.args.get('state')
    pic = request.args.get('pic')
    result = get_works_from_user(1, user_address, 'owner', int(page), pic,
                                 state)
    return result


# 根据用户地址获取创建过的作品
@server.route('/get_created', methods=['GET'])
def get_created():
    user_address = request.args.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    page = request.args.get('page')
    state = request.args.get('state')
    pic = request.args.get('pic')
    result = get_works_from_user(1, user_address, 'creator', int(page), pic,
                                 state)
    return result


# 根据地址获取藏品
@server.route('/get_collection', methods=['GET'])
def get_collection():
    user_address = request.args.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    page = request.args.get('page')
    state = request.args.get('state')
    pic = request.args.get('pic')
    result = get_works_from_user(2, user_address, 'collector', int(page), pic,
                                 state)
    return result


# 用户收藏艺术家作品
@server.route('/append_works', methods=['POST'])
def append_works():
    data = request.get_json()
    token_id = int(data['token_id'])
    user_address = Web3.toChecksumAddress(data['user_address'])
    doc = works.find_one({'_id': token_id})
    collector = doc['collector']
    if user_address not in collector:
        collector.append(user_address)
    works.update_one({'_id': token_id}, {'$set': {'collector': collector}})
    return ''


# 用户取消收藏艺术家作品
@server.route('/remove_works', methods=['POST'])
def remove_works():
    data = request.get_json()
    token_id = int(data['token_id'])
    user_address = Web3.toChecksumAddress(data['user_address'])
    doc = works.find_one({'_id': token_id})
    collector = doc['collector']
    if user_address in collector:
        collector.remove(user_address)
    works.update_one({'_id': token_id}, {'$set': {'collector': collector}})
    return ''


# 根据tokenid获取画布信息
@server.route('/get_canvas', methods=['GET'])
def get_canvas():
    token = request.args.get('token_id')
    token = int(token)
    return_list = []
    num = works.count_documents({'_id': token})
    if num == 0:
        return 'The token_id does not exist'
    cursor = works.find_one({'_id': token})
    if cursor['type'] == 'canvas':
        return_list.append({
            'type': 'address',
            'user_address': cursor['owner']
        })
        return_list.append({'type': 'canvas', 'name': cursor['name']})
        layer_arr = cursor['data']
        for i in layer_arr:
            doc = works.find_one({'_id': i})
            data = doc['data']
            for j in range(len(data)):
                data[j] = url + data[j]
            json_dict = {
                'type': 'layer',
                'name': doc['name'],
                'str': data,
                'introduce': doc['introduce'],
            }
            return_list.append(json_dict)
        return jsonify(return_list)
    if cursor['type'] == 'single':
        json_dict = {
            'user_address': cursor['owner'],
            'type': 'single',
            'name': cursor['name'],
            'str': url + cursor['data'],
            'introduce': cursor['introduce'],
        }
        return json_dict
    return {}


# 保存用户信息
@server.route('/save_info', methods=['POST'])
def save_info():
    data = request.get_json()
    user_address = Web3.toChecksumAddress(data['user_address'])
    count = user.count_documents({'_id': user_address})
    src = data['avatar']
    if src:
        image_hash = get_hash(src, False)
        new_src = src.split(',')[1]
        image_type = src.split('/')[1].split(';')[0]
        image_data = base64.b64decode(new_src)
        image_file = '{}/avatar/{}.{}'.format(folder, image_hash, image_type)
        with open(image_file, 'wb') as f:
            f.write(image_data)
        src = image_file[6:]
    if count == 0:
        user.insert_one({
            '_id': user_address,
            'area': data['area'],
            'avatar': src,
            'email': data['email'],
            'introduce': data['introduce'],
            'name': data['name'],
            'ts': data['ts'],
            'web': data['web'],
            'follows': [],
            'fans': [],
        })
        return '1'
    else:
        user.update_one(
            {'_id': user_address},
            {
                '$set': {
                    'area': data['area'],
                    'avatar': src,
                    'email': data['email'],
                    'introduce': data['introduce'],
                    'name': data['name'],
                    'ts': data['ts'],
                    'web': data['web'],
                }
            },
        )
        return '0'


# 获取用户信息
@server.route('/get_info', methods=['GET'])
def get_info():
    user_address = request.args.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    num = user.count_documents({'_id': user_address})
    if num != 0:
        doc = user.find_one({'_id': user_address})
        if doc['avatar']:
            doc['avatar'] = url + doc['avatar']
        return doc
    else:
        return {}


# 根据token_id获取作品信息
@server.route('/get_works', methods=['GET'])
def get_works():
    token = request.args.get('token_id')
    token = int(token)
    num = works.count_documents({'_id': token})
    if num == 0:
        return 'The token_id does not exist'
    cursor = works.find_one({'_id': token})
    try:
        json_dict = {
            'token_id': cursor['_id'],
            'name': cursor['name'],
            'type': cursor['type'],
            'introduce': cursor['introduce'],
            'create_time': cursor['create_time'],
            'creator_name': info(cursor['creator'], 'name'),
            'creator_address': cursor['creator'],
            'creator_avatar': info(cursor['creator'], 'avatar'),
            'owner_name': info(cursor['owner'], 'name'),
            'owner_address': cursor['owner'],
            'owner_avatar': info(cursor['owner'], 'avatar'),
            'state1': cursor['state1'],
            'state2': cursor['state2'],
        }
        if json_dict['state1'] == 1:
            json_dict['buy_price'] = int(cursor['buy_price'])
        if not json_dict['state2'] == 0:
            json_dict['auction_start_time'] = cursor['auction_start_time']
            json_dict['auction_end_time'] = cursor['auction_end_time']
            json_dict['start_price'] = int(cursor['start_price'])
            if json_dict['state2'] == 2:
                json_dict['max_price'] = int(cursor['max_price'])
            if json_dict['state2'] == 3:
                json_dict['end_price'] = int(cursor['end_price'])
        if cursor['type'] == 'layer':
            json_data = cursor['json_data']
            data = json.loads(json_data)
            json_dict['canvas_token_id'] = data['canvas_token_id']
            doc = works.find_one({'_id': data['canvas_token_id']})
            canvas_name = doc['name']
            json_dict['canvas_name'] = canvas_name
            json_dict['width'] = cursor['width']
            json_dict['height'] = cursor['height']
            data = cursor['data']
            for i in range(len(data)):
                data[i] = url + data[i]
            json_dict['layer'] = data
            return json_dict
        elif cursor['type'] == 'canvas':
            json_dict['width'] = cursor['width']
            json_dict['height'] = cursor['height']
            layer_arr = cursor['data']
            arr = []
            for i in layer_arr:
                doc = works.find_one({'_id': i})
                data = doc['data']
                for j in range(len(data)):
                    data[j] = url + data[j]
                arr.append(data)
            json_dict['layers'] = arr
            return json_dict
        else:
            json_dict['single'] = url + cursor['data']
            return json_dict
    except Exception as e:
        server.logger.exception(e)
    return {}


# 接受交易更新数据库
@server.route('/update_coll', methods=['POST'])
def update_coll():
    data = request.get_json()
    token = data['token_id']
    address_from = Web3.toChecksumAddress(data['address_from'])
    address_to = Web3.toChecksumAddress(data['address_to'])
    number = user.count_documents({'_id': address_to})
    if number == 0:
        add_user(address_to)
    try:
        doc = works.find_one({'_id': token})
        if doc['owner'] == address_from:
            works.update_one({'_id': token}, {'$set': {'owner': address_to}})
    except Exception as e:
        server.logger.exception(e)
    return ''


# 打入黑洞
@server.route('/burn_nft', methods=['POST'])
def burn_nft():
    data = request.get_json()
    token_id = int(data['token_id'])
    works.delete_one({'_id': token_id})
    return ''


# 用户关注艺术家
@server.route('/follow_user', methods=['POST'])
def follow_user():
    data = request.get_json()
    follow_from = Web3.toChecksumAddress(data['from'])
    follow_to = Web3.toChecksumAddress(data['to'])
    follow_doc = user.find_one({'_id': follow_from})
    follows = follow_doc['follows']
    if follow_to not in follows:
        follows.append(follow_to)
    user.update_one({'_id': follow_from}, {'$set': {'follows': follows}})
    fans_doc = user.find_one({'_id': follow_to})
    fans = fans_doc['fans']
    if follow_from not in fans:
        fans.append(follow_from)
    user.update_one({'_id': follow_to}, {'$set': {'fans': fans}})
    return ''


# 用户取消关注艺术家
@server.route('/unfollow_user', methods=['POST'])
def unfollow_user():
    data = request.get_json()
    unfollow_from = Web3.toChecksumAddress(data['from'])
    unfollow_to = Web3.toChecksumAddress(data['to'])
    unfollow_doc = user.find_one({'_id': unfollow_from})
    follows = unfollow_doc['follows']
    if unfollow_to in follows:
        follows.remove(unfollow_to)
    user.update_one({'_id': unfollow_from}, {'$set': {'follows': follows}})
    fans_doc = user.find_one({'_id': unfollow_to})
    fans = fans_doc['fans']
    if unfollow_from in fans:
        fans.remove(unfollow_from)
    user.update_one({'_id': unfollow_to}, {'$set': {'fans': fans}})
    return ''


# 获取用户的关注列表
@server.route('/get_follows', methods=['GET'])
def get_follows():
    user_address = Web3.toChecksumAddress(request.args.get('user_address'))
    doc = user.find_one({'_id': user_address})
    follows = doc['follows']
    return_list = []
    for follow in follows:
        return_list.append({
            'user_address': follow,
            'avatar': info(follow, 'avatar'),
            'name': info(follow, 'name')
        })
    return jsonify(return_list)


# 获取用户粉丝列表
@server.route('/get_fans', methods=['GET'])
def get_fans():
    user_address = Web3.toChecksumAddress(request.args.get('user_address'))
    doc = user.find_one({'_id': user_address})
    fans = doc['fans']
    return_list = []
    for fan in fans:
        return_list.append({
            'user_address': fan,
            'avatar': info(fan, 'avatar'),
            'name': info(fan, 'name')
        })
    return jsonify(return_list)


# 获取交易记录
@server.route('/get_record', methods=['GET'])
def get_record():
    token_id = request.args.get('token_id')
    user_address = request.args.get('user_address')
    return_list = []
    if token_id:
        token_id = int(token_id)
        cursor = record.find({'token_id': token_id}).sort([('time', -1)])
    else:
        user_address = w3.toChecksumAddress(user_address)
        cursor = record.find({
            '$or': [{
                'from': user_address
            }, {
                'to': user_address
            }]
        }).sort([('time', -1)])
    for doc in cursor:
        return_list.append(doc)
    return jsonify(return_list)


# 获取用户未铸币的token
@server.route('/get_approved', methods=['GET'])
def get_approved():
    user_address = request.args.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    return_list = []
    cursor = approve.find({'user_address': user_address}).sort([('_id', 1)])
    for doc in cursor:
        return_list.append(doc)
    return jsonify(return_list)


# 获取用户收益
@server.route('/get_income', methods=['GET'])
def get_income():
    user_address = request.args.get('user_address')
    user_address = w3.toChecksumAddress(user_address)
    cursor1 = sell.find({'user_address':user_address})
    cursor2 = profit.find({'user_address':user_address})
    sell_list = []
    profit_list = []
    total_sell = 0
    total_profit = 0
    for doc in cursor1:
        doc['price'] = int(doc['price'])
        sell_list.append(doc)
        total_sell = total_sell + int(doc['price'])
    for doc in cursor2:
        doc['price'] = int(doc['price'])
        profit_list.append(doc)
        total_profit = total_profit + int(doc['price'])
    return dict({
        'sell': sell_list,
        'total_sell': total_sell,
        'profit': profit_list,
        'total_profit': total_profit,
        'total': total_sell + total_profit
    })


t1 = Thread(target=pin_str_to_ipfs)
t1.start()
t2 = Thread(target=pin_file_to_ipfs)
t2.start()