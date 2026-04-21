import logging
import traceback
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config

class MongoDB:
    """
      An Async Database using Motor
    """
    
    def __init__(self) -> None:
        self._db = None
        self._client = None
    
    @property
    def db(self):
        # Klien baru dibuat saat dipanggil pertama kali di dalam uvloop
        if self._db is None:
            self._db = AsyncIOMotorClient(Config.DATABASE_URL)
        return self._db
        
    @property
    def client(self):
        if self._client is None:
            self._client = self.db[Config.BOT_USERNAME]
        return self._client
    
    async def initialize_users(self) -> dict:
        exists = await self.db[Config.BOT_USERNAME].users.find_one({})
        if exists:
            user_data = {} 
            # Menggunakan AsyncIOMotorCursor
            cursor = self.db[Config.BOT_USERNAME].users.find({})
            async for row in cursor:
                uid = row["_id"]
                del row["_id"]
                user_data[uid] = row
            return user_data
        return {}
    
    async def authorize_chats(self, user_id: int, remove=False) -> bool:
        if remove:
            # Memperbaiki typo "pull" menjadi "$pull"
            ret = await self.client.music.update_one(
                {"_id": Config.BOT_USERNAME}, 
                {"$pull": {"AUTH_CHATS": user_id}}, 
                upsert=True
            )
            return bool(ret)
        
        ret = await self.client.music.update_one(
            {"_id": Config.BOT_USERNAME}, 
            {"$addToSet": {"AUTH_CHATS": user_id}}, 
            upsert=True
        )
        return bool(ret)
    
    async def authorize_users(self, user_id: int, remove=False) -> bool:
        if remove:
            # Memperbaiki typo "pull" menjadi "$pull"
            ret = await self.client.music.update_one(
                {"_id": Config.BOT_USERNAME}, 
                {"$pull": {"AUTH_USERS": user_id}}, 
                upsert=True
            )
            return bool(ret)
        
        ret = await self.client.music.update_one(
            {"_id": Config.BOT_USERNAME}, 
            {"$addToSet": {"AUTH_USERS": user_id}}, 
            upsert=True
        )
        return bool(ret)
    
    async def set_variable(self, key: str, value: str|bool|int|None) -> bool:
        ret = await self.client.music.update_one(
            {"_id": Config.BOT_USERNAME}, 
            {"$set": {key: value}}, 
            upsert=True
        )
        return bool(ret)
    
    async def get_variable(self, query: None|dict = None) -> dict:
        if not query:
            query = {}
            
        # Motor menggunakan to_list() untuk mengekstrak seluruh data cursor secara efisien
        data_list = await self.client.music.find(query).to_list(length=None)
        data_dict = {}
        
        for data in data_list:
            data_dict = data
        if "_id" in data_dict:
            data_dict.pop("_id")
        return data_dict

    async def save_user_settings(self, user_id: int=0, data: dict=None) -> None:
        if data is None:
            data = {}
        user_id = int(user_id) if isinstance(user_id, str) else user_id
        try:
            await self.db[Config.BOT_USERNAME].users.update_one(
                {"_id": user_id}, 
                {"$set": data}, 
                upsert=True
            )
        except Exception:
            logging.info(traceback.format_exc())

    # --- PENAMBAHAN FUNGSI BARU DI SINI ---
    async def get_user_settings(self, user_id: int) -> dict:
        """
        Mengambil pengaturan user dari database.
        """
        user_id = int(user_id) if isinstance(user_id, str) else user_id
        try:
            # Mencari data user berdasarkan _id (user_id)
            data = await self.db[Config.BOT_USERNAME].users.find_one({"_id": user_id})
            return data if data else {}
        except Exception:
            logging.info(traceback.format_exc())
            return {}
    # --------------------------------------

    async def get_bot_setting(self, key: str):
        """Mengambil pengaturan global bot dari koleksi music."""
        try:
            doc = await self.client.music.find_one({"_id": Config.BOT_USERNAME})
            return doc.get(key) if doc else None
        except Exception:
            return None

    async def set_bot_setting(self, key: str, value):
        """Menyimpan pengaturan global bot ke koleksi music."""
        try:
            await self.client.music.update_one(
                {"_id": Config.BOT_USERNAME},
                {"$set": {key: value}},
                upsert=True
            )
        except Exception:
            logging.info(traceback.format_exc())

database = MongoDB()
