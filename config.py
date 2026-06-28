import os

class Config:
    BOT_TOKEN = os.getenv('BOT_TOKEN', '')
    ADMIN_IDS = [
        int(x) for x in os.getenv('ADMIN_IDS', '').split(',')
        if x.strip().isdigit()
    ]
    VIP_GROUP_IDS = [
        int(x) for x in os.getenv('VIP_GROUP_IDS', '').split(',')
        if x.strip().lstrip('-').isdigit()
    ]
