from blackjack.db.card_data_access import *

cursor = connection.cursor()

user_id = 6969

def test_add_card():
    card1 = (user_id, CARD_HOLDER.DEALER.name, 10)
    card2 = (user_id, CARD_HOLDER.USER.name, 0)

    # Add 2 cards
    add_card(*card1)
    add_card(*card2)

    # Check
    expected = [card1, card2]
    result = cursor.execute('SELECT * FROM cards WHERE user_id=?',(user_id,)).fetchall()

    if(len(result) != 2 or result[0] != expected[0] or result[1] != expected[1]):
        raise ValueError('Error(test_add_card), error adding the cards')

    cursor.execute('DELETE FROM cards WHERE user_id=?', (user_id,))
    return

def test_remove_card():
    add_card(user_id, CARD_HOLDER.DEALER.name, 10)
    add_card(user_id, CARD_HOLDER.USER.name, 10)
    add_card(user_id, CARD_HOLDER.DEALER.name, 0)

    cards_added_to_db = len(cursor.execute('SELECT * FROM cards WHERE user_id=?', (user_id,)).fetchall())
    # test that the cards were added in the first place
    if cards_added_to_db != 3:
        raise ValueError('Error(test_remove_card), error when initially adding cards')

    remove_cards(user_id)
    expected = 0
    result = len(cursor.execute('SELECT * FROM cards WHERE user_id=?', (user_id,)).fetchall())

    # tests if all cards were removed
    if expected != result:
        raise ValueError('Error(test_remove_card), error removing the cards')

    return

def test_get_cards():
    add_card(user_id, CARD_HOLDER.DEALER.name, 1)
    add_card(user_id, CARD_HOLDER.USER.name, 3)
    add_card(user_id, CARD_HOLDER.DEALER.name, 2)
    add_card(user_id, CARD_HOLDER.USER.name, 4)

    result_dealer_cards = get_cards(user_id, CARD_HOLDER.DEALER.name)
    expected_dealer_cards = [1,2]

    result_user_cards = get_cards(user_id, CARD_HOLDER.USER.name)
    expected_user_cards = [3,4]

    if(result_dealer_cards != expected_dealer_cards or result_user_cards != expected_user_cards):
        raise ValueError('Error(test_get_cards), did not get the expected dealer/user cards')

    remove_cards(user_id)
    connection.commit()
    return



test_add_card()
test_remove_card()
test_get_cards()
print("CARD DATA ACCESS TESTS FINISHED")