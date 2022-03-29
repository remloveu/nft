import pymongo
import json

client = pymongo.MongoClient('127.0.0.1', 27017)
db = client.heco
works = db.works

ipfs_url = 'https://icarusart.mypinata.cloud/ipfs/'

cursor = works.find()
for doc in cursor:
    doc['token_id'] = doc['_id']
    doc['json_data'] = json.loads(doc['json_data'])
    if doc['type'] == 'single':
        doc['json_data']['image'] = ipfs_url + doc['json_data']['hash'][0]
    else:
        doc['json_data']['image'] = ''
    doc['contract'] = 'v1'
    doc['metadata_hash'] = ipfs_url + doc['metadata_hash']
    works.delete_one({'_id':doc['_id']})
    del doc['_id']
    works.insert_one(doc)

print('success')