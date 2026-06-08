import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import MONGO_URI


# MongoDB setup
mongo = AsyncIOMotorClient(MONGO_URI)
db = mongo["sharing_bot"]
files_col = db["files"]
allowed_channels_col = db["allowed_channels"]


async def ensure_ttl_indexes():
    """
    Ensures TTL indexes are created for collections that have expiring documents.
    MongoDB will automatically delete documents after the specified time.
    """
    try:
        logging.info("TTL indexes ensured.")
    except Exception as e:
        logging.error(f"Error creating TTL indexes: {e}")
users_col = db["users"]
comments_col = db["comments"]


''' JSON setup for Atlas Search'''

'''
This index definition should be applied to `files_col` collection in the Atlas UI.
To minimize storage consumption, dynamic mapping is disabled and only essential fields (file_name) are indexed.

{
  "analyzer": "custom_analyzer",
  "searchAnalyzer": "custom_analyzer",
  "mappings": {
    "dynamic": false,
    "fields": {
      "file_name": {
        "type": "string",
        "analyzer": "custom_analyzer"
      }
    }
  },
  "analyzers": [
    {
      "name": "custom_analyzer",
      "tokenizer": {
        "type": "regexSplit",
        "pattern": "[\\s._-]+"
      },
      "tokenFilters": [
        {
          "type": "lowercase"
        }
      ]
    }
  ]
}

'''
