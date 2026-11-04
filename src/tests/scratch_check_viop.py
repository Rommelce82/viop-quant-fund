import asyncio
import json
import sys
import os

# Workspace root'u sys.path'e ekle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from src.data.fintables_mcp import FintablesMCPClient

async def check_viop_tables():
    client = FintablesMCPClient()
    
    # 1. Bilgi şemasını sorgula
    sql = """
    SELECT table_schema, table_name 
    FROM information_schema.tables 
    WHERE table_name ILIKE '%viop%' 
       OR table_name ILIKE '%teminat%' 
       OR table_name ILIKE '%margin%' 
       OR table_name ILIKE '%sozlesme%'
    ORDER BY table_name;
    """
    res = await client.call_tool('veri_sorgula', {'sql': sql, 'purpose': 'viop tablolarini kesfet'})
    print("TABLES FOUND:")
    print(res)

if __name__ == "__main__":
    asyncio.run(check_viop_tables())
