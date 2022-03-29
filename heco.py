import pymongo
import os
import base64
import imageio
import cv2
from shutil import copyfile
import moviepy.editor as mp
from datetime import datetime
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
from threading import Thread

# 连接mongodb
client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
# 作品信息集合
works = db.works
# user信息集合
user = db.user
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
single_address = res['single_contract']
black_address = '0xe7a5B85218a9F685D89630e7312b5686cdD49175'
contract = w3.eth.contract(address=address, abi=abi)
single_contract = w3.eth.contract(address=single_address, abi=abi)
file_queue = Queue()
str_queue = Queue()
wallet_address = res['wallet_address']
private_key = res['private_key']
endpoint = 'https://api.pinata.cloud/'
host = res['host']
url = host + 'data/'
small_url = url + 'small/'
single_url = url + 'single/small/'
headers = {
    'pinata_api_key': res['pinata_api_key'],
    'pinata_secret_api_key': res['pinata_secret_api_key'],
}
tx_url = res['tx_url']
pinata_url = res['pinata_url']
web_url = res['web_url']


# 生成多图层metadata
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
        'external_url': web_url + str(token_id) + '?contractVersion=v1',
        'animation_url': '',
    }
    return json.dumps(parameters)


# 生成单图层metadata
def make_single_json(name,
              data_type,
              creator,
              create_time,
              introduce,
              data_hash,
              tags,
              file_type,
              width=0,
              height=0):
    parameters = {
        'name': name,
        'type': data_type,
        'creator': creator,
        'create_time': create_time,
        'description': introduce,
        'hash': data_hash,
        'tags': tags,
        'file_type': file_type,
        'width': width,
        'height': height,
        'image': pinata_url + data_hash[0],
        'animation_url': '',
    }
    return json.dumps(parameters)


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
        if not file_queue.empty():
            file_path = file_queue.get()
            url = endpoint + 'pinning/pinFileToIPFS'
            f = open(file_path, 'rb')
            files = {'file': f}
            requests.post(url, files=files, headers=headers)
            f.close()
        time.sleep(3)


def pin_str_to_ipfs():
    while 1:
        if not str_queue.empty():
            meta_str = str_queue.get()
            url = endpoint + 'pinning/pinFileToIPFS'
            files = {'file': meta_str}
            requests.post(url, files=files, headers=headers)
        time.sleep(3)


# 根据地址获取具体信息
def info(user_address, param):
    user_count = user.count_documents({'_id':user_address})
    if user_count == 0:
        add_user(user_address)
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
    cursor = works.find(cursor_dict).sort([('contract',-1),('token_id', 1)])
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
                    'token_id': doc['token_id'],
                    'name': doc['name'],
                    'type': doc['type'],
                    'creator_address': doc['creator'],
                    'creator_avatar': info(doc['creator'], 'avatar'),
                    'owner_address': doc['owner'],
                    'owner_avatar': info(doc['owner'], 'avatar'),
                    'state1': doc['state1'],
                    'state2': doc['state2'],
                    'contractVersion': doc['contract'],
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
                        layer_doc = works.find_one({'token_id': i, 'contract':'v1'})
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
                        if doc['contract'] == 'v2':
                            json_dict['single'] = single_url + single_data
                            json_dict['edition'] = doc['edition']
                            json_dict['edition_count'] = doc['edition_count']
                        else:
                            json_dict['single'] = small_url + single_data
                    else:
                        if doc['contract'] == 'v2':
                            json_dict['single'] = single_url + doc['data']
                            json_dict['edition'] = doc['edition']
                            json_dict['edition_count'] = doc['edition_count']
                        else :
                            json_dict['single'] = small_url + doc['data']
                return_list.append(json_dict)
            except Exception as e:
                server.logger.exception('token_id:{},contract:{} {}'.format(doc['token_id'],doc['contract'],e))
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
        'contract': 'v1',
        'token_id': token_id,
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
    while 1:
        try:
            nonce = w3.eth.get_transaction_count(wallet_address, 'pending')
            break
        except Exception:
            time.sleep(0.1)
            pass
    transact = {'gas': 160000, 'nonce': nonce}
    transaction = contract.functions.whitelistTokenForCreator(
        user_address, main_token, second_num, 15, 5).buildTransaction(transact)
    tx = w3.eth.account.sign_transaction(transaction, private_key)
    tx_hash = w3.eth.send_raw_transaction(tx.rawTransaction)
    tx_hash = tx_hash.hex()
    result = w3.eth.wait_for_transaction_receipt(tx_hash)
    return result['status']


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


def stamp_to_str(time_stamp):
    time_temp = float(time_stamp)/1000
    time_str = datetime.utcfromtimestamp(time_temp).strftime('%Y-%m-%d %H:%M:%S.%f')
    return time_str + ' UTC'


# 获取token_id
@server.route('/get_token', methods=['POST'])
def get_token():
    # 获取当前token_id
    lock = request.environ['HTTP_FLASK_LOCK']
    data = request.form.get('address')
    data = json.loads(data)
    user_address = Web3.toChecksumAddress(data['user_address'])
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
    token_id = token_num
    status = approve_token(user_address, token_id, len(layer))
    if status == 0:
        lock.release()
        return 'Authorization failed!'
    token_number.update_one(
        {'_id': 1}, {'$set': {
            'token_num': token_num + len(layer) + 1
        }})
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
            file_queue.put(new_path)
            path_arr.append(new_path[6:])
            layer_arr.append(layer_hash)
        doc = layer[index]
        layer_json = make_json(doc['name'], 'layer', user_address, create_time,
                               doc['introduce'], layer_token_id, token_id,
                               layer_arr, [], 'png', width, height)
        str_queue.put(layer_json)
        layer_metadata_hash = get_hash(layer_json, False)
        try:
            add_works(layer_token_id, path_arr, pinata_url + layer_metadata_hash,
                      user_address, doc['introduce'], create_time, doc['name'],
                      json.loads(layer_json), 'layer', False, width, height)
        except Exception as e:
            server.logger.exception(e)
        json_dict = {
            'type': 'layer',
            'token_id': layer_token_id,
            'layer_metadata_hash': pinata_url + layer_metadata_hash,
        }
        return_list.append(json_dict)
        index = index + 1
    canvas_json = make_json(canvas['name'], 'canvas', user_address,
                            stamp_to_str(create_time), canvas['introduce'], token_id,
                            token_id, layer_token, [], '', width, height)
    str_queue.put(canvas_json)
    canvas_metadata_hash = get_hash(canvas_json, False)
    canvas_dict = {
        'type': 'canvas',
        'token_id': token_id,
        'canvas_metadata_hash': pinata_url + canvas_metadata_hash,
    }
    return_list.append(canvas_dict)
    try:
        add_works(token_id, layer_token, pinata_url + canvas_metadata_hash,
                  user_address,canvas['introduce'], create_time, canvas['name'],
                  json.loads(canvas_json), 'canvas', False, width, height)
    except Exception as e:
        server.logger.exception(e)
    return jsonify(return_list)


# 获取单一铸币的token
@server.route('/single_token', methods=['POST'])
def single_token():
    # 获取当前token_id
    user_address = request.form.get('user_address')
    user_address = Web3.toChecksumAddress(user_address)
    name = request.form.get('name')
    introduce = request.form.get('introduce')
    create_time = request.form.get('create_time')
    create_time = int(create_time)
    single_file = request.files['str']
    file_name = secure_filename(single_file.filename)
    img = file_name.rsplit('.')[-1].lower()
    now = int(time.time())
    if not os.path.exists('{}/temp/{}'.format(folder, user_address)):
        os.mkdir('{}/temp/{}'.format(folder, user_address))
    temp_path = '{}/temp/{}/{}.{}'.format(folder, user_address, now, img)
    single_file.save(temp_path)
    single_hash = get_hash(temp_path, True)
    if img in ['jpg', 'jpeg', 'gif', 'png']:
        image = Image.open(temp_path)
        width, height = image.size
    else:
        vcap = cv2.VideoCapture(temp_path)
        if vcap.isOpened():
            width = int(vcap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(vcap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    if os.path.exists(temp_path):
        os.remove(temp_path)
    single_json = make_single_json(name, 'single', user_address, stamp_to_str(create_time),
                            introduce,[single_hash], [], img, width, height)
    str_queue.put(single_json)
    single_metadata_hash = get_hash(single_json, False)
    json_dict = {
        'token_id': '',
        'single_metadata_hash': pinata_url + single_metadata_hash,
    }
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


# 根据tokenid获取画布信息 x
@server.route('/get_canvas', methods=['GET'])
def get_canvas():
    token = request.args.get('token_id')
    token = int(token)
    single = request.args.get('single')
    return_list = []
    cursor_dict = {'token_id': token}
    if single == 'true':
        cursor_dict['contract'] = 'b'
    else:
        cursor_dict['contract'] = 'a'
    num = works.count_documents(cursor_dict)
    if num == 0:
        return 'The token_id does not exist'
    cursor = works.find_one(cursor_dict)
    if cursor['type'] == 'canvas':
        return_list.append({
            'type': 'address',
            'user_address': cursor['owner']
        })
        return_list.append({
            'type': 'canvas',
            'name': cursor['name'],
            'contractVersion': cursor['contract']
        })
        layer_arr = cursor['data']
        for i in layer_arr:
            doc = works.find_one({'token_id': i,'contract':'v1'})
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
            'contractVersion': cursor['contract'],
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
        if src[:4] == 'data':
            image_hash = get_hash(src, False)
            new_src = src.split(',')[1]
            image_type = src.split('/')[1].split(';')[0]
            image_data = base64.b64decode(new_src)
            image_file = '{}/avatar/{}.{}'.format(folder, image_hash, image_type)
            with open(image_file, 'wb') as f:
                f.write(image_data)
            src = image_file[6:]
        else:
            src = src[32:]
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
        return ''
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
        return ''


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
    contract_version = request.args.get('contractVersion')
    token = int(token)
    cursor_dict = {'token_id': token, 'contract':contract_version}
    num = works.count_documents(cursor_dict)
    if num == 0:
        return {}
    cursor = works.find_one(cursor_dict)
    try:
        json_dict = {
            'token_id': cursor['token_id'],
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
            'contractVersion': cursor['contract'],
            'metadata_url': cursor['metadata_hash'],
            'image_url': cursor['json_data']['image']
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
            try:
                data = json.loads(json_data)
            except Exception:
                data = json_data
            json_dict['canvas_token_id'] = data['canvas_token_id']
            doc = works.find_one({'token_id': data['canvas_token_id'], 'contract':'v1'})
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
                doc = works.find_one({'token_id': i,'contract':'v1'})
                data = doc['data']
                for j in range(len(data)):
                    data[j] = url + data[j]
                arr.append(data)
            json_dict['layers'] = arr
            return json_dict
        else:
            if contract_version == 'v2':
                json_dict['single'] = url + 'single/' + cursor['data']
                json_dict['edition'] = cursor['edition']
                json_dict['edition_count'] = cursor['edition_count']
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
    contract_version = data['contractVersion']
    address_from = Web3.toChecksumAddress(data['address_from'])
    address_to = Web3.toChecksumAddress(data['address_to'])
    number = user.count_documents({'_id': address_to})
    if number == 0:
        add_user(address_to)
    try:
        doc = works.find_one({'token_id': token, 'contract':contract_version})
        if doc['owner'] == address_from:
            works.update_one({'token_id': token, 'contract': contract_version}, {'$set': {'owner': address_to}})
    except Exception as e:
        server.logger.exception(e)
    return ''


# 打入黑洞
@server.route('/burn_nft', methods=['POST'])
def burn_nft():
    data = request.get_json()
    token_id = data['token_id']
    contract_version = data['contractVersion']
    works.delete_one({'token_id': token_id, 'contract':contract_version})
    return ''


@server.route('/get_latest', methods=['GET'])
def get_latest():
    cursor = works.find({'contract':'v2'}).sort([('token_id',-1)])
    index = 1
    return_list = []
    for doc in cursor:
        if index > 3:
            break
        else:
            token_id = doc['token_id']
            params = {
                'token_id': token_id,
                'contractVersion': 'v2'
            }
            data = requests.get(host + 'get_works', params = params).text
            data = json.loads(data)
            return_list.append(data)
            index = index + 1
    return jsonify(return_list)


t1 = Thread(target=pin_str_to_ipfs)
t1.start()
t2 = Thread(target=pin_file_to_ipfs)
t2.start()
