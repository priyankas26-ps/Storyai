import os
from pymongo import MongoClient
from pymongo.errors import PyMongoError

_client = None

def db():
    global _client
    if _client is None:
        _client = MongoClient(os.environ.get('MONGODB_URI', 'mongodb://localhost:27017'), serverSelectionTimeoutMS=4000)
    return _client[os.environ.get('MONGODB_DB', 'storyai_pro')]
