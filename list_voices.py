import asyncio
import edge_tts

async def list_voices():
    voices = await edge_tts.list_voices()
    # Filter for English voices
    en_voices = [v for v in voices if v['Locale'].startswith('en-')]
    for v in en_voices:
        print(f"{v['ShortName']} - {v['Gender']} - {v['FriendlyName']}")

asyncio.run(list_voices())
