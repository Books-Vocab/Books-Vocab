import time
from pathlib import Path
from src.kg.cards import CardStore, Card
from src.kg.api import app

def test_option_b():
    test_dir = Path("./test_data_option_b")
    store = CardStore(test_dir)
    
    # 1. Provide a dummy Card
    card = store.add(content="test_word", meaning="test meaning")
    print(f"Created card: {card.id}, content: {card.content}")
    
    # Simulate step 1 enrichment fetching taking time
    # User deletes the card during this time
    store.delete(card.id)
    print("Deleted card manually.")
    
    # Simulate backend finishing the enrichment
    # We test `update` method directly how api.py uses it
    updated_card = store.update(card.id, pos="n.", note="This is a test note.")
    
    if updated_card is None:
        print("SUCCESS: store.update returned None, card was not updated because it's deleted.")
    else:
        print("FAIL: store.update updated a deleted card!")

    # Verify state
    db_card = store.get(card.id)
    if db_card.is_deleted and db_card.pos is None and db_card.note is None:
        print("SUCCESS: Card in DB remains deleted and without enrichment data.")
    else:
        print(f"FAIL: Card state incorrect. is_deleted={db_card.is_deleted}, pos={db_card.pos}, note={db_card.note}")

if __name__ == "__main__":
    test_option_b()
