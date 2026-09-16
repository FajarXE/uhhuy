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
        """
        Dikosongkan untuk mencegah Memory Leak / RAM Bloat.
        Data user tidak lagi dimuat semua saat bot start, melainkan via Lazy-Load (JIT).
        """
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

    # --- PENAMBAHAN FUNGSI STATE CANCEL ---
    async def add_cancel_task(self, task_id: str):
        """Menyimpan ID tugas yang dibatalkan ke MongoDB"""
        try:
            # Menggunakan collection baru bernama 'cancelled_tasks'
            await self.client.cancelled_tasks.update_one(
                {'_id': task_id}, 
                {'$set': {'status': 'cancelled'}}, 
                upsert=True
            )
        except Exception as e:
            logging.error(f"Gagal menyimpan cancel task ke DB: {e}")

    async def load_all_cancels(self) -> set:
        """Memuat semua sinyal batal dari MongoDB saat bot restart"""
        cancels = set()
        try:
            cursor = self.client.cancelled_tasks.find({})
            async for doc in cursor:
                cancels.add(doc['_id'])
        except Exception as e:
            logging.error(f"Gagal memuat cancel tasks dari DB: {e}")
        return cancels

    async def clear_all_cancels(self):
        """Membersihkan semua memori sinyal batal (Dipanggil oleh clear_board)"""
        try:
            await self.client.cancelled_tasks.delete_many({})
        except Exception as e:
            logging.error(f"Gagal menghapus cancel tasks di DB: {e}")
    # --------------------------------------

    # --- PENAMBAHAN FUNGSI STATE RADAR UI ---
    async def save_ui_state(self, chat_id: int, message_id: int, page: int = 1):
        """Menyimpan ID pesan Radar Papan Global agar tidak hilang saat restart"""
        try:
            await self.client.ui_states.update_one(
                {'_id': chat_id},
                {'$set': {'message_id': message_id, 'page': page}},
                upsert=True
            )
        except Exception as e:
            logging.error(f"Gagal menyimpan UI state: {e}")

    async def load_all_ui_states(self) -> dict:
        """Memuat semua status Radar UI dari MongoDB"""
        states = {}
        try:
            cursor = self.client.ui_states.find({})
            async for doc in cursor:
                states[doc['_id']] = {
                    'message_id': doc['message_id'], 
                    'page': doc.get('page', 1)
                }
        except Exception as e:
            logging.error(f"Gagal memuat UI states: {e}")
        return states

    async def remove_ui_state(self, chat_id: int):
        """Menghapus memori Radar UI jika tugas sudah selesai atau panel ditutup"""
        try:
            await self.client.ui_states.delete_one({'_id': chat_id})
        except Exception:
            pass
    # ----------------------------------------

database = MongoDB()
